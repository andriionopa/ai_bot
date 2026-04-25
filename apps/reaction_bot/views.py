from __future__ import annotations

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.reaction_bot.models import AccountChannelBinding, ReactionJob, ReactionLog
from apps.reaction_bot.serializers import (
    AccountChannelBindingSerializer,
    ReactionJobSerializer,
    ReactionLogSerializer,
    ReactionOverviewSerializer,
)
from apps.reaction_bot.services import overview_payload, start_reaction_job, stop_reaction_job


class OwnerQuerysetMixin:
    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ReactionJobViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReactionJobSerializer
    queryset = ReactionJob.objects.all().prefetch_related("accounts")

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        job = start_reaction_job(self.get_object())
        return Response(self.get_serializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        job = stop_reaction_job(self.get_object())
        return Response(self.get_serializer(job).data)

    @action(detail=False, methods=["delete"], url_path="clear_finished")
    def clear_finished(self, request):
        deleted, _ = self.get_queryset().exclude(
            status=ReactionJob.Status.RUNNING
        ).delete()
        return Response({"deleted": deleted})


class ReactionLogViewSet(OwnerQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReactionLogSerializer
    queryset = ReactionLog.objects.select_related("account", "job")

    def get_queryset(self):
        queryset = super().get_queryset().order_by("created_at")
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        return queryset[:500]


class AccountChannelBindingViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AccountChannelBindingSerializer
    queryset = AccountChannelBinding.objects.select_related("account")

    def get_queryset(self):
        return super().get_queryset().order_by("account__label", "channel_username")


class ReactionOverviewViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        payload = overview_payload(request.user)
        serializer = ReactionOverviewSerializer(payload, context={"request": request})
        return Response(serializer.data)
