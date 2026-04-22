from django.conf import settings
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.realtime.logging import publish_log_event


class PublishLogSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=("debug", "info", "warning", "error"), default="info")
    source = serializers.CharField(max_length=80, default="manual")
    message = serializers.CharField(max_length=settings.REALTIME_LOG_MESSAGE_MAX_LENGTH)

    def validate_source(self, value):
        return " ".join(value.strip().split())

    def validate_message(self, value):
        value = " ".join(value.strip().split())
        if not value:
            raise serializers.ValidationError("Message is required.")
        return value


class PublishLogView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PublishLogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        publish_log_event(payload)
        return Response(payload, status=status.HTTP_202_ACCEPTED)
