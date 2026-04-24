from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.channel_parser.views import (
    ChannelCollectionTemplateViewSet,
    ChannelParserJobViewSet,
    ChannelParserLogViewSet,
    ChannelParserOverviewViewSet,
    ChannelParserTemplateViewSet,
    ParsedChannelViewSet,
)

router = DefaultRouter()
router.register("jobs", ChannelParserJobViewSet, basename="channel-parser-job")
router.register("results", ParsedChannelViewSet, basename="channel-parser-result")
router.register("logs", ChannelParserLogViewSet, basename="channel-parser-log")
router.register("templates", ChannelParserTemplateViewSet, basename="channel-parser-template")
router.register("channel-templates", ChannelCollectionTemplateViewSet, basename="channel-collection-template")

channel_parser_overview = ChannelParserOverviewViewSet.as_view({"get": "list"})
channel_parser_job_add = ChannelParserJobViewSet.as_view({"post": "create"})
channel_parser_job_start = ChannelParserJobViewSet.as_view({"post": "start"})
channel_parser_job_stop = ChannelParserJobViewSet.as_view({"post": "stop"})
channel_parser_job_export = ChannelParserJobViewSet.as_view({"get": "export"})
channel_parser_results_clear = ParsedChannelViewSet.as_view({"post": "clear"})

urlpatterns = [
    path("overview/", channel_parser_overview, name="channel-parser-overview"),
    path("jobs/add/", channel_parser_job_add, name="channel-parser-job-add"),
    path("jobs/<int:pk>/start/", channel_parser_job_start, name="channel-parser-job-start"),
    path("jobs/<int:pk>/stop/", channel_parser_job_stop, name="channel-parser-job-stop"),
    path("jobs/<int:pk>/export/", channel_parser_job_export, name="channel-parser-job-export"),
    path("results/clear/", channel_parser_results_clear, name="channel-parser-results-clear"),
    path("", include(router.urls)),
]
