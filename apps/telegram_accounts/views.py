from pathlib import Path

from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.realtime.logging import publish_log_event
from apps.telegram_accounts.models import AccountRoleTemplate, Proxy, TelegramAccount
from apps.telegram_accounts.serializers import (
    AccountRoleTemplateSerializer,
    FarmOverviewSerializer,
    AccountRuntimeEventCreateSerializer,
    ProxySerializer,
    TelegramAccountAttachSerializer,
    TelegramAccountBulkDetachSerializer,
    TelegramAccountChatMessagesSerializer,
    TelegramAccountCreateChannelSerializer,
    TelegramAccountCompleteAuthSerializer,
    TelegramAccountDialogListSerializer,
    TelegramAccountHealthSerializer,
    TelegramAccountProxyAssignSerializer,
    TelegramAccountSendMessageSerializer,
    TelegramAccountSerializer,
    TelegramAccountSet2FASerializer,
)
from apps.telegram_accounts.services import (
    assign_account_proxy,
    attach_account_via_session,
    bulk_detach_accounts,
    check_account_proxy_connectivity,
    cleanup_stale_accounts,
    complete_credentials_auth,
    create_account_channel,
    delete_account_with_files,
    list_account_chat_messages,
    list_account_dialogs,
    recalculate_account_state,
    register_account_runtime_event,
    resend_credentials_code,
    send_account_chat_message,
    set_account_cloud_password,
    start_credentials_auth,
    refresh_account_profile_snapshot,
    check_account_spam_block,
    telegram_user_facing_error,
    telegram_runtime_workdir,
)
from apps.telegram_accounts.tasks import ping_proxy_task, register_account_runtime_event_task
from apps.channel_parser.models import ChannelParserJob
from apps.message_parser.models import MessageParserJob
from apps.warmup.models import WarmupPlan


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


class AccountRoleTemplateViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AccountRoleTemplateSerializer
    queryset = AccountRoleTemplate.objects.all()


class TelegramAccountViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TelegramAccountSerializer
    queryset = TelegramAccount.objects.select_related("proxy", "role_template").prefetch_related("health_events", "profile_drafts")

    def get_queryset(self):
        running_warmup = WarmupPlan.objects.filter(
            accounts=OuterRef("pk"),
            status=WarmupPlan.Status.RUNNING,
        )
        running_parsing = ChannelParserJob.objects.filter(
            accounts=OuterRef("pk"),
            status=ChannelParserJob.Status.RUNNING,
        )
        running_message_parsing = MessageParserJob.objects.filter(
            accounts=OuterRef("pk"),
            status=MessageParserJob.Status.RUNNING,
        )
        return super().get_queryset().annotate(
            _has_running_warmup=Exists(running_warmup),
            _has_running_parsing=Exists(running_parsing) | Exists(running_message_parsing),
        )

    def get_parsers(self):
        if getattr(self, "action", None) == "add":
            return [MultiPartParser(), FormParser(), JSONParser()]
        return super().get_parsers()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset()).order_by("-attached_at", "-created_at")
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def perform_destroy(self, instance):
        delete_account_with_files(instance)

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
        serializer = FarmOverviewSerializer(payload, context={"request": request})
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
        return Response(TelegramAccountSerializer(account, context={"request": request}).data, status=status.HTTP_201_CREATED)

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
        return Response(TelegramAccountSerializer(account, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="resend-code")
    def resend_code(self, request, pk=None):
        account = self.get_object()
        if not account.phone_number:
            return Response(
                {"detail": "Для переавторизації потрібен номер телефону акаунта. Для session-only акаунта імпортуйте нову .session."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        return Response(TelegramAccountSerializer(account, context={"request": request}).data)

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
        return Response(TelegramAccountSerializer(account, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="proxy-check")
    def proxy_check(self, request, pk=None):
        account = self.get_object()
        result = check_account_proxy_connectivity(account)
        publish_log_event(
            {
                "level": "info" if result.get("ok") else "warning",
                "source": "proxy",
                "message": f"{account.label}: proxy check -> {'ok' if result.get('ok') else 'failed'}",
                "account_id": account.id,
                "result": result,
            }
        )
        response_status = status.HTTP_200_OK if result.get("ok") else status.HTTP_400_BAD_REQUEST
        return Response(result, status=response_status)

    @action(detail=True, methods=["post"], url_path="create-channel")
    def create_channel(self, request, pk=None):
        account = self.get_object()
        if not account.is_connected:
            return Response(
                {"detail": "Акаунт не підключений. Спочатку переавторизуйте або імпортуйте валідну .session."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TelegramAccountCreateChannelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_account_channel(account, **serializer.validated_data)
            register_account_runtime_event(
                account,
                event_type="success",
                metadata={"source": "create_channel", "channel": result},
            )
            publish_log_event(
                {
                    "level": "info",
                    "source": "telegram",
                    "message": f"{account.label}: created channel {result.get('title')}",
                    "account_id": account.id,
                    "result": result,
                }
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except Exception as exc:
            error_text = str(exc)
            account.last_auth_error = error_text
            account.last_error_at = timezone.now()
            account.save(update_fields=["last_auth_error", "last_error_at"])
            return Response(
                {"detail": telegram_user_facing_error(exc), "telegram_error": error_text},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"], url_path="set-2fa")
    def set_2fa(self, request, pk=None):
        account = self.get_object()
        if not account.is_connected:
            return Response(
                {"detail": "Акаунт не підключений. Спочатку переавторизуйте або імпортуйте валідну .session."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TelegramAccountSet2FASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = set_account_cloud_password(account, **serializer.validated_data)
            register_account_runtime_event(
                account,
                event_type="success",
                metadata={"source": "set_2fa", "enabled": result.get("enabled")},
            )
            publish_log_event(
                {
                    "level": "info",
                    "source": "telegram",
                    "message": f"{account.label}: 2FA password updated",
                    "account_id": account.id,
                    "result": result,
                }
            )
            return Response(result)
        except Exception as exc:
            error_text = str(exc)
            account.last_auth_error = error_text
            account.last_error_at = timezone.now()
            account.save(update_fields=["last_auth_error", "last_error_at"])
            return Response(
                {"detail": telegram_user_facing_error(exc), "telegram_error": error_text},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        if account.is_connected:
            try:
                account = refresh_account_profile_snapshot(account)
            except Exception as exc:
                error_text = str(exc)
                account.last_auth_error = error_text
                account.last_error_at = timezone.now()
                update_fields = ["last_auth_error", "last_error_at"]
                if "AUTH_KEY_UNREGISTERED" in error_text:
                    account.auth_state = TelegramAccount.AuthState.FAILED
                    account.status = TelegramAccount.Status.DRAFT
                    update_fields.extend(["auth_state", "status"])
                account.save(update_fields=update_fields)
                if "FLOOD_WAIT" in error_text.upper():
                    register_account_runtime_event(
                        account,
                        event_type="flood_wait",
                        metadata={"source": "health_check", "error": error_text},
                    )
        account = recalculate_account_state(account)
        serializer = TelegramAccountHealthSerializer(account)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="export-session")
    def export_session(self, request, pk=None):
        account = self.get_object()
        runtime_path = telegram_runtime_workdir() / f"{account.session_name}.session"
        uploaded_path = Path(account.session_file.path) if account.session_file else None
        session_path = runtime_path if runtime_path.exists() else uploaded_path
        if not session_path or not session_path.exists():
            return Response({"detail": "Session file is not available for this account."}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(session_path.open("rb"), as_attachment=True, filename=f"{account.session_name}.session")
        return response

    @action(detail=True, methods=["post"], url_path="spam-check")
    def spam_check(self, request, pk=None):
        account = self.get_object()
        if not account.is_connected:
            return Response(
                {"detail": "Акаунт не підключений. Спочатку переавторизуйте або імпортуйте валідну .session."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = check_account_spam_block(account)
            event_type = "spam_block" if result.get("limited") else "success"
            register_account_runtime_event(account, event_type=event_type, metadata={"source": "spam_check", **result})
            publish_log_event(
                {
                    "level": "warning" if result.get("limited") else "info",
                    "source": "account-health",
                    "message": f"{account.label}: spam block check -> {'limited' if result.get('limited') else 'clear'}",
                    "account_id": account.id,
                    "result": result,
                }
            )
            return Response(result)
        except Exception as exc:
            error_text = str(exc)
            account.last_auth_error = error_text
            account.last_error_at = timezone.now()
            update_fields = ["last_auth_error", "last_error_at"]
            detail = error_text
            if "AUTH_KEY_UNREGISTERED" in error_text:
                account.auth_state = TelegramAccount.AuthState.FAILED
                account.status = TelegramAccount.Status.DRAFT
                update_fields.extend(["auth_state", "status"])
                detail = "Сесія Telegram невалідна. Переавторизуйте акаунт або імпортуйте нову .session."
            elif "FLOOD_WAIT" in error_text.upper():
                register_account_runtime_event(account, event_type="flood_wait", metadata={"source": "spam_check", "error": error_text})
                detail = "Telegram тимчасово обмежив запити для цього акаунта. FloodWait записано в health."
            account.save(update_fields=update_fields)
            return Response({"detail": detail, "telegram_error": error_text}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"], url_path="dialogs")
    def dialogs(self, request, pk=None):
        account = self.get_object()
        if not account.is_connected:
            return Response(
                {"detail": "Акаунт не підключений. Спочатку переавторизуйте або імпортуйте валідну .session."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TelegramAccountDialogListSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            dialogs = list_account_dialogs(account, limit=serializer.validated_data["limit"])
            return Response({"dialogs": dialogs})
        except Exception as exc:
            error_text = str(exc)
            account.last_auth_error = error_text
            account.last_error_at = timezone.now()
            account.save(update_fields=["last_auth_error", "last_error_at"])
            return Response(
                {"detail": telegram_user_facing_error(exc), "telegram_error": error_text},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        account = self.get_object()
        if not account.is_connected:
            return Response(
                {"detail": "Акаунт не підключений. Спочатку переавторизуйте або імпортуйте валідну .session."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TelegramAccountChatMessagesSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            payload = list_account_chat_messages(account, **serializer.validated_data)
            return Response(payload)
        except Exception as exc:
            error_text = str(exc)
            account.last_auth_error = error_text
            account.last_error_at = timezone.now()
            account.save(update_fields=["last_auth_error", "last_error_at"])
            return Response({"detail": error_text}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="send-message")
    def send_message(self, request, pk=None):
        account = self.get_object()
        if not account.is_connected:
            return Response(
                {"detail": "Акаунт не підключений. Спочатку переавторизуйте або імпортуйте валідну .session."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = TelegramAccountSendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            message = send_account_chat_message(account, **serializer.validated_data)
            register_account_runtime_event(
                account,
                event_type="success",
                metadata={"source": "web_chat", "chat_id": serializer.validated_data["chat_id"]},
            )
            publish_log_event(
                {
                    "level": "info",
                    "source": "telegram-web",
                    "message": f"{account.label}: web chat message sent",
                    "account_id": account.id,
                    "chat_id": serializer.validated_data["chat_id"],
                }
            )
            return Response({"message": message}, status=status.HTTP_201_CREATED)
        except Exception as exc:
            error_text = str(exc)
            account.last_auth_error = error_text
            account.last_error_at = timezone.now()
            account.save(update_fields=["last_auth_error", "last_error_at"])
            return Response({"detail": error_text}, status=status.HTTP_400_BAD_REQUEST)

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
