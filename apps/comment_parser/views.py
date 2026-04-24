from __future__ import annotations

from django.http import HttpResponse
from django.utils.encoding import smart_str
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.comment_parser.models import CommentParserJob, CommentParserLog, ParsedCommenter
from apps.comment_parser.serializers import (
    CommentParserJobSerializer,
    CommentParserLogSerializer,
    CommentParserOverviewSerializer,
    ParsedCommenterSerializer,
)
from apps.comment_parser.services import export_results, overview_payload, start_parser_job, stop_parser_job


class OwnerQuerysetMixin:
    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CommentParserJobViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CommentParserJobSerializer
    queryset = CommentParserJob.objects.all().prefetch_related("accounts")

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        job = start_parser_job(self.get_object())
        return Response(self.get_serializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        job = stop_parser_job(self.get_object())
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        job = self.get_object()
        export_format = request.query_params.get("export_format") or request.GET.get("export_format") or "csv"
        filename, content_type, body = export_results(job, export_format=export_format)
        response = HttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{smart_str(filename)}"'
        return response


class ParsedCommenterViewSet(OwnerQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ParsedCommenterSerializer
    queryset = ParsedCommenter.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-comment_count", "-last_comment_at")
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        return queryset

    @action(detail=False, methods=["post"])
    def clear(self, request):
        job_id = request.data.get("job_id")
        queryset = self.get_queryset()
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        deleted, _ = queryset.delete()
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


class CommentParserLogViewSet(OwnerQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CommentParserLogSerializer
    queryset = CommentParserLog.objects.select_related("account", "job")

    def get_queryset(self):
        queryset = super().get_queryset().order_by("created_at")
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        return queryset[:500]


class CommentParserOverviewViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        payload = overview_payload(request.user)
        serializer = CommentParserOverviewSerializer(payload, context={"request": request})
        return Response(serializer.data)
