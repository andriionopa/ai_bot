from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.reaction_bot.views import (
    AccountChannelBindingViewSet,
    ReactionJobViewSet,
    ReactionLogViewSet,
    ReactionOverviewViewSet,
)

router = DefaultRouter()
router.register(r"jobs", ReactionJobViewSet, basename="reaction-job")
router.register(r"logs", ReactionLogViewSet, basename="reaction-log")
router.register(r"bindings", AccountChannelBindingViewSet, basename="reaction-binding")
router.register(r"overview", ReactionOverviewViewSet, basename="reaction-overview")

urlpatterns = [
    path("", include(router.urls)),
]
