from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.comment_parser.views import (
    CommentParserJobViewSet,
    CommentParserLogViewSet,
    CommentParserOverviewViewSet,
    ParsedCommenterViewSet,
)

router = DefaultRouter()
router.register("jobs", CommentParserJobViewSet, basename="comment-parser-job")
router.register("results", ParsedCommenterViewSet, basename="comment-parser-result")
router.register("logs", CommentParserLogViewSet, basename="comment-parser-log")

comment_parser_overview = CommentParserOverviewViewSet.as_view({"get": "list"})
comment_parser_job_add = CommentParserJobViewSet.as_view({"post": "create"})
comment_parser_job_start = CommentParserJobViewSet.as_view({"post": "start"})
comment_parser_job_stop = CommentParserJobViewSet.as_view({"post": "stop"})
comment_parser_job_export = CommentParserJobViewSet.as_view({"get": "export"})
comment_parser_results_clear = ParsedCommenterViewSet.as_view({"post": "clear"})

urlpatterns = [
    path("overview/", comment_parser_overview, name="comment-parser-overview"),
    path("jobs/add/", comment_parser_job_add, name="comment-parser-job-add"),
    path("jobs/<int:pk>/start/", comment_parser_job_start, name="comment-parser-job-start"),
    path("jobs/<int:pk>/stop/", comment_parser_job_stop, name="comment-parser-job-stop"),
    path("jobs/<int:pk>/export/", comment_parser_job_export, name="comment-parser-job-export"),
    path("results/clear/", comment_parser_results_clear, name="comment-parser-results-clear"),
    path("", include(router.urls)),
]
