from __future__ import annotations

import json

import redis
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.realtime.logging import LOG_CHANNEL_NAME, fan_out_log_event


class Command(BaseCommand):
    help = "Subscribe to Redis pub/sub and forward log events to Channels groups."

    def handle(self, *args, **options):
        client = redis.from_url(settings.REDIS_URL)
        pubsub = client.pubsub()
        pubsub.subscribe(LOG_CHANNEL_NAME)
        self.stdout.write(self.style.SUCCESS(f"Subscribed to {LOG_CHANNEL_NAME}"))

        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            payload = json.loads(message["data"])
            fan_out_log_event(payload)

