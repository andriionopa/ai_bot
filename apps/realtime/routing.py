from django.urls import path

from apps.realtime.consumers import LogConsumer

websocket_urlpatterns = [
    path("ws/logs/", LogConsumer.as_asgi()),
]

