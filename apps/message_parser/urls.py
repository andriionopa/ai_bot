from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.message_parser.views import (
    MessageParserJobViewSet,
    MessageParserLogViewSet,
    MessageParserOverviewViewSet,
    ParsedUserViewSet,
)

router = DefaultRouter()
router.register("jobs", MessageParserJobViewSet, basename="message-parser-job")
router.register("results", ParsedUserViewSet, basename="message-parser-result")
router.register("logs", MessageParserLogViewSet, basename="message-parser-log")

message_parser_overview = MessageParserOverviewViewSet.as_view({"get": "list"})
message_parser_job_add = MessageParserJobViewSet.as_view({"post": "create"})
message_parser_job_start = MessageParserJobViewSet.as_view({"post": "start"})
message_parser_job_stop = MessageParserJobViewSet.as_view({"post": "stop"})
message_parser_job_export = MessageParserJobViewSet.as_view({"get": "export"})
message_parser_results_clear = ParsedUserViewSet.as_view({"post": "clear"})

urlpatterns = [
    path("overview/", message_parser_overview, name="message-parser-overview"),
    path("jobs/add/", message_parser_job_add, name="message-parser-job-add"),
    path("jobs/<int:pk>/start/", message_parser_job_start, name="message-parser-job-start"),
    path("jobs/<int:pk>/stop/", message_parser_job_stop, name="message-parser-job-stop"),
    path("jobs/<int:pk>/export/", message_parser_job_export, name="message-parser-job-export"),
    path("results/clear/", message_parser_results_clear, name="message-parser-results-clear"),
    path("", include(router.urls)),
]
