from __future__ import annotations

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.neuro_commenting.models import (
    NeuroCommentBlacklist,
    NeuroCommentJob,
    NeuroCommentLog,
    NeuroCommentPrompt,
)
from apps.neuro_commenting.serializers import (
    NeuroCommentBlacklistSerializer,
    NeuroCommentJobSerializer,
    NeuroCommentLogSerializer,
    NeuroCommentOverviewSerializer,
    NeuroCommentPromptSerializer,
)
from apps.neuro_commenting.services import (
    overview_payload,
    start_neuro_comment_job,
    stop_neuro_comment_job,
)


class OwnerQuerysetMixin:
    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class NeuroCommentJobViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NeuroCommentJobSerializer
    queryset = NeuroCommentJob.objects.all().prefetch_related("accounts", "selected_prompts")

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        job = start_neuro_comment_job(self.get_object())
        return Response(self.get_serializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        job = stop_neuro_comment_job(self.get_object())
        return Response(self.get_serializer(job).data)

    @action(detail=False, methods=["delete"], url_path="clear_finished")
    def clear_finished(self, request):
        deleted, _ = self.get_queryset().exclude(
            status=NeuroCommentJob.Status.RUNNING
        ).delete()
        return Response({"deleted": deleted})


class NeuroCommentLogViewSet(OwnerQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NeuroCommentLogSerializer
    queryset = NeuroCommentLog.objects.select_related("account", "job")

    def get_queryset(self):
        queryset = super().get_queryset().order_by("created_at")
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        return queryset[:500]


class NeuroCommentPromptViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NeuroCommentPromptSerializer
    queryset = NeuroCommentPrompt.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by("is_system", "name")


class NeuroCommentBlacklistViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NeuroCommentBlacklistSerializer
    queryset = NeuroCommentBlacklist.objects.select_related("account", "job")

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at")

    @action(detail=False, methods=["delete"], url_path="clear_all")
    def clear_all(self, request):
        deleted, _ = self.get_queryset().delete()
        return Response({"deleted": deleted})


class NeuroCommentOverviewViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        payload = overview_payload(request.user)
        serializer = NeuroCommentOverviewSerializer(payload, context={"request": request})
        return Response(serializer.data)
