from __future__ import annotations

import json

import redis
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from redis.exceptions import RedisError


LOG_CHANNEL_NAME = "runtime.logs"


def publish_log_event(payload: dict[str, object]) -> None:
    try:
        client = redis.from_url(settings.REDIS_URL)
        client.publish(LOG_CHANNEL_NAME, json.dumps(payload))
    except RedisError:
        return


def fan_out_log_event(payload: dict[str, object]) -> None:
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)("logs", {"type": "log.message", "payload": payload})
