from django.urls import path

from apps.realtime.views import PublishLogView

urlpatterns = [
    path("logs/publish/", PublishLogView.as_view(), name="publish-log"),
]

