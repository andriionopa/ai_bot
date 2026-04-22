from django.db.models import Count, Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.realtime.logging import publish_log_event
from apps.telegram_accounts.models import Proxy, TelegramAccount
from apps.telegram_accounts.serializers import (
    FarmOverviewSerializer,
    AccountRuntimeEventCreateSerializer,
    ProxySerializer,
    TelegramAccountAttachSerializer,
    TelegramAccountBulkDetachSerializer,
    TelegramAccountCompleteAuthSerializer,
    TelegramAccountHealthSerializer,
    TelegramAccountProxyAssignSerializer,
    TelegramAccountSerializer,
)
from apps.telegram_accounts.services import (
    assign_account_proxy,
    attach_account_via_session,
    bulk_detach_accounts,
    cleanup_stale_accounts,
    complete_credentials_auth,
    recalculate_account_state,
    register_account_runtime_event,
    resend_credentials_code,
    start_credentials_auth,
)
from apps.telegram_accounts.tasks import ping_proxy_task, register_account_runtime_event_task


class OwnerQuerysetMixin:
    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ProxyViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ProxySerializer
    queryset = Proxy.objects.all()

    @action(detail=True, methods=["post"])
    def ping(self, request, pk=None):
        task = ping_proxy_task.delay(int(pk))
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get", "post"], url_path="test")
    def test(self, request, pk=None):
        return self.ping(request, pk=pk)


class TelegramAccountViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TelegramAccountSerializer
    queryset = TelegramAccount.objects.select_related("proxy").prefetch_related("health_events")

    def get_parsers(self):
        if getattr(self, "action", None) == "add":
            return [MultiPartParser(), FormParser(), JSONParser()]
        return super().get_parsers()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset()).order_by("-attached_at", "-created_at")
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        accounts = list(self.get_queryset().order_by("-attached_at", "-created_at"))
        proxies = list(Proxy.objects.filter(owner=request.user).order_by("name"))
        counts = self.get_queryset().aggregate(
            account_count=Count("id"),
            attached_count=Count("id", filter=Q(is_attached=True)),
            connected_count=Count("id", filter=Q(is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED)),
            quarantined_count=Count("id", filter=Q(status=TelegramAccount.Status.QUARANTINE)),
            pending_auth_count=Count(
                "id",
                filter=Q(
                    auth_state__in=[
                        TelegramAccount.AuthState.PENDING_CODE,
                        TelegramAccount.AuthState.PENDING_2FA,
                        TelegramAccount.AuthState.SESSION_UPLOADED,
                    ]
                ),
            ),
        )
        payload = {
            **counts,
            "proxy_count": len(proxies),
            "accounts": accounts,
            "proxies": proxies,
        }
        serializer = FarmOverviewSerializer(payload)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="add")
    def add(self, request):
        serializer = TelegramAccountAttachSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        proxy = data.get("proxy")

        if data["attach_mode"] == TelegramAccount.ConnectSource.SESSION:
            account = attach_account_via_session(
                owner=request.user,
                label=data["label"],
                session_file=data["session_file"],
                phone_number=data.get("phone_number", ""),
                proxy=proxy,
                device_model=data.get("device_model", ""),
                system_version=data.get("system_version", ""),
                randomize_device_profile=data.get("randomize_device_profile", True),
            )
            log_level = "info"
            log_message = f"{account.label}: session uploaded to farm"
        else:
            account = start_credentials_auth(
                owner=request.user,
                label=data["label"],
                phone_number=data["phone_number"],
                proxy=proxy,
                requires_2fa=data.get("requires_2fa", False),
                device_model=data.get("device_model", ""),
                system_version=data.get("system_version", ""),
                randomize_device_profile=data.get("randomize_device_profile", True),
            )
            if account.auth_state == TelegramAccount.AuthState.PENDING_CODE:
                log_level = "info"
                log_message = f"{account.label}: login code sent"
            else:
                log_level = "error"
                log_message = f"{account.label}: failed to send login code"

        publish_log_event(
            {
                "level": log_level,
                "source": "farm",
                "message": log_message,
                "account_id": account.id,
                "auth_state": account.auth_state,
                "status": account.status,
                "error": account.last_auth_error,
            }
        )
        return Response(TelegramAccountSerializer(account).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="complete-auth")
    def complete_auth(self, request, pk=None):
        account = self.get_object()
        serializer = TelegramAccountCompleteAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = complete_credentials_auth(
            account,
            verification_code=serializer.validated_data["verification_code"],
            password_2fa=serializer.validated_data.get("password_2fa", ""),
        )
        publish_log_event(
            {
                "level": "info" if account.auth_state == TelegramAccount.AuthState.CONNECTED else "warning",
                "source": "farm",
                "message": f"{account.label}: auth state -> {account.get_auth_state_display()}",
                "account_id": account.id,
                "auth_state": account.auth_state,
                "status": account.status,
            }
        )
        return Response(TelegramAccountSerializer(account).data)

    @action(detail=True, methods=["post"], url_path="resend-code")
    def resend_code(self, request, pk=None):
        account = self.get_object()
        account = resend_credentials_code(account)
        publish_log_event(
            {
                "level": "info" if account.auth_state == TelegramAccount.AuthState.PENDING_CODE else "error",
                "source": "farm",
                "message": f"{account.label}: code resend -> {account.get_auth_state_display()}",
                "account_id": account.id,
                "auth_state": account.auth_state,
                "status": account.status,
                "error": account.last_auth_error,
            }
        )
        return Response(TelegramAccountSerializer(account).data)

    @action(detail=True, methods=["post"], url_path="proxy")
    def assign_proxy(self, request, pk=None):
        account = self.get_object()
        serializer = TelegramAccountProxyAssignSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        account = assign_account_proxy(account, serializer.validated_data.get("proxy"))
        publish_log_event(
            {
                "level": "info",
                "source": "farm",
                "message": f"{account.label}: proxy updated",
                "account_id": account.id,
                "proxy_id": account.proxy_id,
            }
        )
        return Response(TelegramAccountSerializer(account).data)

    @action(detail=False, methods=["post"], url_path="detach")
    def bulk_detach(self, request):
        serializer = TelegramAccountBulkDetachSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        detached = bulk_detach_accounts(owner=request.user, account_ids=serializer.validated_data["account_ids"])
        publish_log_event(
            {
                "level": "warning",
                "source": "farm",
                "message": f"Detached {detached} account(s) from farm",
                "account_count": detached,
            }
        )
        return Response({"detached_count": detached}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="cleanup-stale")
    def cleanup_stale(self, request):
        deleted = cleanup_stale_accounts(owner=request.user)
        publish_log_event(
            {
                "level": "warning",
                "source": "farm",
                "message": f"Deleted {deleted} stale account(s)",
                "account_count": deleted,
            }
        )
        return Response({"deleted_count": deleted}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def health(self, request, pk=None):
        account = self.get_object()
        account = recalculate_account_state(account)
        serializer = TelegramAccountHealthSerializer(account)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="runtime-events")
    def runtime_events(self, request, pk=None):
        account = self.get_object()
        serializer = AccountRuntimeEventCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data.get("metadata") or {}
        event_type = serializer.validated_data["event_type"]
        try:
            task = register_account_runtime_event_task.delay(account.id, event_type, payload)
        except Exception:
            event = register_account_runtime_event(account, event_type=event_type, metadata=payload)
            publish_log_event(
                {
                    "level": "warning" if event_type != "success" else "info",
                    "source": "account-health",
                    "message": f"{account.label}: {event.get_event_type_display()}",
                    "account_id": account.id,
                    "event_type": event_type,
                    "health_score": account.health_score,
                    "status": account.status,
                    "quarantine_until": account.quarantine_until.isoformat() if account.quarantine_until else None,
                }
            )
            return Response(
                {
                    "mode": "sync",
                    "event_type": event.event_type,
                    "health_score": account.health_score,
                    "status": account.status,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response({"task_id": task.id, "mode": "async"}, status=status.HTTP_202_ACCEPTED)
