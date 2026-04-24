from __future__ import annotations

from django.db.models import Count, Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.telegram_accounts.models import TelegramAccount
from apps.warmup.models import WarmupAction, WarmupLog, WarmupPlan, WarmupPolicy, WarmupTarget
from apps.warmup.serializers import (
    WarmupActionClearSerializer,
    WarmupActionSerializer,
    WarmupOverviewSerializer,
    WarmupPlanSerializer,
    WarmupPolicySerializer,
    WarmupTargetBulkImportSerializer,
    WarmupTargetTemplateImportSerializer,
    WarmupTargetSerializer,
)
from apps.channel_parser.models import ChannelCollectionItem
from apps.warmup.services import (
    clear_warmup_actions,
    pause_warmup_plan,
    plan_queryset_with_counts,
    run_due_warmup_actions,
    start_warmup_plan,
    stop_warmup_plan,
)


class OwnerQuerysetMixin:
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class WarmupPolicyViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    queryset = WarmupPolicy.objects.all()
    serializer_class = WarmupPolicySerializer


class WarmupTargetViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    queryset = WarmupTarget.objects.all()
    serializer_class = WarmupTargetSerializer

    @action(detail=False, methods=["post"], url_path="bulk-import")
    def bulk_import(self, request):
        serializer = WarmupTargetBulkImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visibility = serializer.validated_data["visibility"]
        created: list[WarmupTarget] = []
        skipped = 0
        existing = set(WarmupTarget.objects.filter(owner=request.user).values_list("value", flat=True))

        for target in serializer.validated_data["targets"]:
            if target["value"] in existing:
                skipped += 1
                continue
            created.append(
                WarmupTarget(
                    owner=request.user,
                    title=target["title"],
                    target_type=target["target_type"],
                    visibility=visibility,
                    value=target["value"],
                )
            )
            existing.add(target["value"])

        WarmupTarget.objects.bulk_create(created)
        return Response(
            {
                "created_count": len(created),
                "skipped_count": skipped,
                "targets": WarmupTargetSerializer(created, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="import-channel-template")
    def import_channel_template(self, request):
        serializer = WarmupTargetTemplateImportSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        template = serializer.validated_data["template_id"]
        visibility = serializer.validated_data["visibility"]
        items = ChannelCollectionItem.objects.filter(owner=request.user, template=template).order_by("title", "id")
        created: list[WarmupTarget] = []
        skipped = 0
        existing_by_value = {
            target.value: target.id
            for target in WarmupTarget.objects.filter(owner=request.user).only("id", "value")
        }
        selected_target_ids: list[int] = []

        for item in items:
            value = item.url or (f"@{item.username}" if item.username else "")
            if not value:
                skipped += 1
                continue
            if value in existing_by_value:
                skipped += 1
                selected_target_ids.append(existing_by_value[value])
                continue
            created.append(
                WarmupTarget(
                    owner=request.user,
                    title=(item.title or item.username or value)[:255],
                    target_type=WarmupTarget.TargetType.CHANNEL,
                    visibility=visibility,
                    value=value,
                )
            )

        WarmupTarget.objects.bulk_create(created)
        if created:
            created_targets = list(
                WarmupTarget.objects.filter(
                    owner=request.user,
                    value__in=[target.value for target in created],
                ).only("id", "value", "title", "target_type", "visibility", "status", "created_at", "updated_at")
            )
            selected_target_ids.extend(target.id for target in created_targets)
        else:
            created_targets = []
        return Response(
            {
                "created_count": len(created),
                "skipped_count": skipped,
                "target_ids": selected_target_ids,
                "targets": WarmupTargetSerializer(created_targets, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WarmupPlanViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    queryset = WarmupPlan.objects.select_related("policy").prefetch_related("accounts", "targets")
    serializer_class = WarmupPlanSerializer

    def get_queryset(self):
        return plan_queryset_with_counts(super().get_queryset()).order_by("-created_at")

    def get_serializer_context(self):
        return {"request": self.request, **super().get_serializer_context()}

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        plan = start_warmup_plan(self.get_object())
        plan = plan_queryset_with_counts(WarmupPlan.objects.filter(pk=plan.pk)).get()
        return Response(WarmupPlanSerializer(plan, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        plan = pause_warmup_plan(self.get_object())
        plan = plan_queryset_with_counts(WarmupPlan.objects.filter(pk=plan.pk)).get()
        return Response(WarmupPlanSerializer(plan, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        payload = stop_warmup_plan(self.get_object(), purge_redis=bool(request.data.get("purge_redis", True)))
        return Response(payload, status=status.HTTP_200_OK)


class WarmupActionViewSet(OwnerQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = WarmupAction.objects.select_related("plan", "account", "target")
    serializer_class = WarmupActionSerializer

    def get_queryset(self):
        return super().get_queryset().order_by("-scheduled_for", "-created_at")[:200]

    @action(detail=False, methods=["post"], url_path="run-due")
    def run_due(self, request):
        limit = min(max(int(request.data.get("limit", 20)), 1), 100)
        force = bool(request.data.get("force", False))
        payload = run_due_warmup_actions(owner=request.user, limit=limit, force=force)
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="clear")
    def clear(self, request):
        serializer = WarmupActionClearSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = clear_warmup_actions(
            owner=request.user,
            mode=serializer.validated_data["mode"],
            clear_logs=serializer.validated_data["clear_logs"],
            purge_redis=serializer.validated_data["purge_redis"],
        )
        return Response(payload, status=status.HTTP_200_OK)


class WarmupOverviewViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        policy_qs = WarmupPolicy.objects.filter(owner=request.user).order_by("-created_at")
        target_qs = WarmupTarget.objects.filter(owner=request.user).order_by("-created_at")
        plan_qs = plan_queryset_with_counts(
            WarmupPlan.objects.filter(owner=request.user).select_related("policy").prefetch_related("accounts", "targets")
        ).order_by("-created_at")[:20]
        action_qs = (
            WarmupAction.objects.filter(owner=request.user)
            .select_related("plan", "account", "target")
            .order_by("-scheduled_for", "-created_at")[:50]
        )
        log_qs = (
            WarmupLog.objects.filter(owner=request.user)
            .select_related("plan", "action", "account")
            .order_by("-created_at")[:120]
        )
        account_qs = TelegramAccount.objects.filter(owner=request.user)
        payload = {
            "policies": policy_qs,
            "targets": target_qs,
            "plans": plan_qs,
            "actions": action_qs,
            "logs": log_qs,
            "connected_accounts": account_qs.filter(is_attached=True, auth_state=TelegramAccount.AuthState.CONNECTED).count(),
            "running_plans": WarmupPlan.objects.filter(owner=request.user, status=WarmupPlan.Status.RUNNING).count(),
            "queued_actions": WarmupAction.objects.filter(owner=request.user, status=WarmupAction.Status.QUEUED).count(),
            "quarantined_accounts": account_qs.filter(status=TelegramAccount.Status.QUARANTINE).count(),
        }
        return Response(WarmupOverviewSerializer(payload, context={"request": request}).data, status=status.HTTP_200_OK)
