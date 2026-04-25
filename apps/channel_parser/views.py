from __future__ import annotations

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils.encoding import smart_str
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.channel_parser.models import (
    ChannelCollectionItem,
    ChannelCollectionTemplate,
    ChannelParserJob,
    ChannelParserLog,
    ChannelParserTemplate,
    ParsedChannel,
)
from apps.channel_parser.serializers import (
    ChannelCollectionTemplateSerializer,
    ChannelParserJobSerializer,
    ChannelParserLogSerializer,
    ChannelParserOverviewSerializer,
    ChannelParserTemplateSerializer,
    ParsedChannelSerializer,
)
from apps.channel_parser.services import export_results, overview_payload, start_parser_job, stop_parser_job


class OwnerQuerysetMixin:
    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ChannelParserJobViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChannelParserJobSerializer
    queryset = ChannelParserJob.objects.all().prefetch_related("accounts")

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


class ParsedChannelViewSet(OwnerQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ParsedChannelSerializer
    queryset = ParsedChannel.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-created_at")
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


class ChannelParserLogViewSet(OwnerQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChannelParserLogSerializer
    queryset = ChannelParserLog.objects.select_related("account", "job")

    def get_queryset(self):
        queryset = super().get_queryset().order_by("created_at")
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        return queryset[:500]


class ChannelParserTemplateViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChannelParserTemplateSerializer
    queryset = ChannelParserTemplate.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by("name", "-created_at")


class ChannelCollectionTemplateViewSet(OwnerQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChannelCollectionTemplateSerializer
    queryset = ChannelCollectionTemplate.objects.all()

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(item_count=Count("items", distinct=True))
            .prefetch_related("items")
            .order_by("name", "-created_at")
        )

    @action(detail=False, methods=["post"], url_path="save-sources")
    def save_sources(self, request):
        from django.db.models import Q

        template_id = request.data.get("template_id")
        name = " ".join(str(request.data.get("name") or "").split())
        sources = request.data.get("sources") or []

        if template_id:
            template = self.get_queryset().filter(pk=template_id).first()
            if not template:
                return Response({"detail": "Шаблон не знайдено."}, status=status.HTTP_404_NOT_FOUND)
        else:
            if not name:
                return Response({"detail": "Вкажіть назву шаблону."}, status=status.HTTP_400_BAD_REQUEST)
            template, _ = ChannelCollectionTemplate.objects.get_or_create(owner=request.user, name=name)

        added = 0
        skipped = 0
        for source in sources:
            source = str(source or "").strip()
            if not source:
                continue
            if source.startswith("http"):
                url = source
                username = ""
                telegram_id = None
                title = url
            elif source.lstrip("-").isdigit():
                telegram_id = int(source)
                username = ""
                url = ""
                title = source
            else:
                username = source.lstrip("@")
                url = f"https://t.me/{username}"
                telegram_id = None
                title = f"@{username}"

            q = Q()
            if url:
                q |= Q(url=url)
            if username:
                q |= Q(username=username)
            if telegram_id is not None:
                q |= Q(telegram_id=telegram_id)

            if q and ChannelCollectionItem.objects.filter(owner=request.user, template=template).filter(q).exists():
                skipped += 1
                continue

            ChannelCollectionItem.objects.create(
                owner=request.user,
                template=template,
                title=title,
                username=username,
                url=url,
                telegram_id=telegram_id,
            )
            added += 1

        template = (
            ChannelCollectionTemplate.objects.filter(owner=request.user, pk=template.pk)
            .annotate(item_count=Count("items", distinct=True))
            .prefetch_related("items")
            .get()
        )
        serializer = self.get_serializer(template)
        return Response({"template": serializer.data, "added": added, "skipped": skipped})

    @action(detail=False, methods=["post"], url_path="attach-user-results")
    def attach_user_results(self, request):
        from apps.comment_parser.models import ParsedCommenter
        from apps.message_parser.models import ParsedUser

        template_id = request.data.get("template_id")
        name = " ".join(str(request.data.get("name") or "").split())
        result_ids = request.data.get("result_ids") or []
        select_all = bool(request.data.get("select_all"))
        job_id = request.data.get("job_id")
        parser_type = request.data.get("parser_type", "comments")

        if template_id:
            template = self.get_queryset().filter(pk=template_id).first()
            if not template:
                return Response({"detail": "Шаблон не знайдено."}, status=status.HTTP_404_NOT_FOUND)
        else:
            if not name:
                return Response({"detail": "Вкажіть назву шаблону."}, status=status.HTTP_400_BAD_REQUEST)
            template, _ = ChannelCollectionTemplate.objects.get_or_create(owner=request.user, name=name)

        Model = ParsedCommenter if parser_type == "comments" else ParsedUser
        results = Model.objects.filter(owner=request.user)
        if job_id:
            results = results.filter(job_id=job_id)
        if not select_all:
            normalized_ids = [int(i) for i in result_ids if str(i).isdigit()]
            if not normalized_ids:
                return Response({"detail": "Оберіть хоча б один результат."}, status=status.HTTP_400_BAD_REQUEST)
            results = results.filter(id__in=normalized_ids)

        results = list(results)
        if not results:
            return Response({"detail": "Немає результатів для додавання."}, status=status.HTTP_400_BAD_REQUEST)

        added = 0
        skipped = 0
        for result in results:
            username = result.username or ""
            url = result.profile_url or ""
            title = result.full_name or (f"@{username}" if username else str(result.telegram_user_id or ""))

            q = Q()
            if username:
                q |= Q(username=username)
            if url:
                q |= Q(url=url)
            if q and ChannelCollectionItem.objects.filter(owner=request.user, template=template).filter(q).exists():
                skipped += 1
                continue

            ChannelCollectionItem.objects.create(
                owner=request.user,
                template=template,
                title=title,
                username=username,
                url=url,
            )
            added += 1

        template = (
            ChannelCollectionTemplate.objects.filter(owner=request.user, pk=template.pk)
            .annotate(item_count=Count("items", distinct=True))
            .prefetch_related("items")
            .get()
        )
        serializer = self.get_serializer(template)
        return Response({"template": serializer.data, "added": added, "skipped": skipped})

    @action(detail=False, methods=["post"], url_path="attach-results")
    def attach_results(self, request):
        template_id = request.data.get("template_id")
        name = " ".join(str(request.data.get("name") or "").split())
        result_ids = request.data.get("result_ids") or []
        select_all = bool(request.data.get("select_all"))
        job_id = request.data.get("job_id")

        if template_id:
            template = self.get_queryset().filter(pk=template_id).first()
            if not template:
                return Response({"detail": "Шаблон каналів не знайдено."}, status=status.HTTP_404_NOT_FOUND)
        else:
            if not name:
                return Response({"detail": "Вкажіть назву шаблону каналів."}, status=status.HTTP_400_BAD_REQUEST)
            template, _ = ChannelCollectionTemplate.objects.get_or_create(owner=request.user, name=name)

        results = ParsedChannel.objects.filter(owner=request.user)
        if job_id:
            results = results.filter(job_id=job_id)
        if not select_all:
            normalized_ids = [int(item) for item in result_ids if str(item).isdigit()]
            if not normalized_ids:
                return Response({"detail": "Оберіть хоча б один результат."}, status=status.HTTP_400_BAD_REQUEST)
            results = results.filter(id__in=normalized_ids)

        results = list(results.order_by("-rating", "-subscribers", "title"))
        if not results:
            return Response({"detail": "Немає результатів для додавання."}, status=status.HTTP_400_BAD_REQUEST)

        added = 0
        skipped = 0
        for result in results:
            existing = ChannelCollectionItem.objects.filter(owner=request.user, template=template).filter(
                Q(url=result.url, url__gt="") |
                Q(username=result.username, username__gt="") |
                Q(telegram_id=result.telegram_id, telegram_id__isnull=False)
            ).first()
            if existing:
                skipped += 1
                continue
            ChannelCollectionItem.objects.create(
                owner=request.user,
                template=template,
                source_job=result.job,
                title=result.title,
                username=result.username,
                url=result.url,
                telegram_id=result.telegram_id,
                entity_type=result.entity_type,
                subscribers=result.subscribers,
                rating=result.rating,
                language=result.language,
                activity_level=result.activity_level,
                comments_open=result.comments_open,
                matched_query=result.matched_query,
                description=result.description,
                metadata=result.metadata,
            )
            added += 1

        template = (
            ChannelCollectionTemplate.objects.filter(owner=request.user, pk=template.pk)
            .annotate(item_count=Count("items", distinct=True))
            .prefetch_related("items")
            .get()
        )
        serializer = self.get_serializer(template)
        return Response(
            {"template": serializer.data, "added": added, "skipped": skipped},
            status=status.HTTP_200_OK,
        )


class ChannelParserOverviewViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        payload = overview_payload(request.user)
        serializer = ChannelParserOverviewSerializer(payload, context={"request": request})
        return Response(serializer.data)
