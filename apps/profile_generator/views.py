from __future__ import annotations

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.profile_generator.models import ProfileDraft
from apps.profile_generator.serializers import (
    ProfileDraftCreateSerializer,
    ProfileDraftSerializer,
    ProfilePhotoUploadSerializer,
)
from apps.profile_generator.services import (
    apply_profile_draft,
    generate_profile_bio,
    generate_profile_photo,
    upload_profile_photo,
)
from apps.realtime.logging import publish_log_event


class ProfileDraftViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProfileDraft.objects.select_related("account").all()

    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return ProfileDraftCreateSerializer
        return ProfileDraftSerializer

    def get_parsers(self):
        if getattr(self, "action", None) in {"create", "upload_photo"}:
            return [MultiPartParser(), FormParser(), JSONParser()]
        return super().get_parsers()

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        draft = serializer.save()
        publish_log_event(
            {
                "level": "info",
                "source": "profile-generator",
                "message": f"{draft.account.label}: profile draft created",
                "account_id": draft.account_id,
                "draft_id": draft.id,
            }
        )
        return Response(ProfileDraftSerializer(draft).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="generate-bio")
    def generate_bio(self, request, pk=None):
        draft = generate_profile_bio(self.get_object())
        publish_log_event(
            {
                "level": "info" if draft.bio else "error",
                "source": "profile-generator",
                "message": f"{draft.account.label}: bio generation -> {draft.status}",
                "account_id": draft.account_id,
                "draft_id": draft.id,
                "error": draft.last_error,
            }
        )
        return Response(ProfileDraftSerializer(draft).data)

    @action(detail=True, methods=["post"], url_path="generate-photo")
    def generate_photo(self, request, pk=None):
        draft = self.get_object()
        try:
            draft = generate_profile_photo(draft)
        except Exception as exc:
            draft.mark_failed(str(exc))
        publish_log_event(
            {
                "level": "info" if draft.photo else "error",
                "source": "profile-generator",
                "message": f"{draft.account.label}: photo generation -> {draft.status}",
                "account_id": draft.account_id,
                "draft_id": draft.id,
                "error": draft.last_error,
            }
        )
        return Response(ProfileDraftSerializer(draft).data)

    @action(detail=True, methods=["post"], url_path="upload-photo")
    def upload_photo(self, request, pk=None):
        serializer = ProfilePhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = upload_profile_photo(self.get_object(), serializer.validated_data["photo"])
        return Response(ProfileDraftSerializer(draft).data)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        draft = apply_profile_draft(self.get_object())
        publish_log_event(
            {
                "level": "info" if draft.status == ProfileDraft.Status.APPLIED else "error",
                "source": "profile-generator",
                "message": f"{draft.account.label}: profile apply -> {draft.status}",
                "account_id": draft.account_id,
                "draft_id": draft.id,
                "error": draft.last_error,
            }
        )
        return Response(ProfileDraftSerializer(draft).data)
