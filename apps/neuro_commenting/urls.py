from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.neuro_commenting.views import (
    NeuroCommentBlacklistViewSet,
    NeuroCommentJobViewSet,
    NeuroCommentLogViewSet,
    NeuroCommentOverviewViewSet,
    NeuroCommentPromptViewSet,
)

router = DefaultRouter()
router.register(r"jobs", NeuroCommentJobViewSet, basename="neuro-comment-job")
router.register(r"logs", NeuroCommentLogViewSet, basename="neuro-comment-log")
router.register(r"prompts", NeuroCommentPromptViewSet, basename="neuro-comment-prompt")
router.register(r"blacklist", NeuroCommentBlacklistViewSet, basename="neuro-comment-blacklist")
router.register(r"overview", NeuroCommentOverviewViewSet, basename="neuro-comment-overview")

urlpatterns = [
    path("", include(router.urls)),
]
