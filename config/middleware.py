from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse


class LocalFrontendCorsMiddleware:
    """Minimal CORS for the local Next.js frontend talking to the Django API."""

    allowed_headers = "authorization,content-type,x-csrftoken,x-requested-with"
    allowed_methods = "GET,POST,PUT,PATCH,DELETE,OPTIONS"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" and self._allowed_origin(request):
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        self._patch_headers(request, response)
        return response

    def _allowed_origin(self, request) -> str:
        origin = request.headers.get("Origin", "")
        allowed = set(getattr(settings, "CORS_ALLOWED_ORIGINS", []))
        return origin if origin in allowed else ""

    def _patch_headers(self, request, response) -> None:
        origin = self._allowed_origin(request)
        if not origin:
            return
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Credentials"] = "true"
        response["Access-Control-Allow-Headers"] = self.allowed_headers
        response["Access-Control-Allow-Methods"] = self.allowed_methods
        response["Access-Control-Max-Age"] = "86400"
        response["Vary"] = "Origin"
