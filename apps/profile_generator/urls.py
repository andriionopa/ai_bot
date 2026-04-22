from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.profile_generator.views import ProfileDraftViewSet

router = DefaultRouter()
router.register("drafts", ProfileDraftViewSet, basename="profile-draft")

profile_draft_list = ProfileDraftViewSet.as_view({"get": "list", "post": "create"})
profile_generate_bio = ProfileDraftViewSet.as_view({"post": "generate_bio"})
profile_generate_photo = ProfileDraftViewSet.as_view({"post": "generate_photo"})
profile_upload_photo = ProfileDraftViewSet.as_view({"post": "upload_photo"})
profile_apply = ProfileDraftViewSet.as_view({"post": "apply"})

urlpatterns = [
    path("drafts/", profile_draft_list, name="profile-draft-list"),
    path("drafts/<int:pk>/generate-bio/", profile_generate_bio, name="profile-generate-bio"),
    path("drafts/<int:pk>/generate-photo/", profile_generate_photo, name="profile-generate-photo"),
    path("drafts/<int:pk>/upload-photo/", profile_upload_photo, name="profile-upload-photo"),
    path("drafts/<int:pk>/apply/", profile_apply, name="profile-apply"),
] + router.urls
