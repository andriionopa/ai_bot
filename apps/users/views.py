from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.db import transaction
from urllib.parse import urlencode, urlparse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.forms import EmailLoginForm
from apps.users.models import User
from apps.users.serializers import TelegramLoginSerializer, UserSerializer
from apps.users.services.google import build_google_auth_url, fetch_google_userinfo
from apps.users.services.tokens import build_token_pair


def is_allowed_local_frontend_url(value: str) -> bool:
    parsed = urlparse(value or "")
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.hostname in {"127.0.0.1", "localhost", "192.168.0.192"}


def default_frontend_url(request) -> str:
    frontend = settings.FRONTEND_URL.rstrip("/")
    parsed = urlparse(frontend)
    if parsed.port == 3001:
        return frontend

    host = request.get_host().split(":")[0] or "127.0.0.1"
    if host in {"127.0.0.1", "localhost", "192.168.0.192"}:
        return f"http://{host}:3001"
    return "http://127.0.0.1:3001"


class TelegramLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = TelegramLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        full_name = " ".join(filter(None, [data["first_name"], data.get("last_name", "")])).strip()
        username = data.get("username") or f"tg-{data['id']}"
        email = f"{username}@telegram.local"

        user, _ = User.objects.update_or_create(
            telegram_id=data["id"],
            defaults={
                "email": email,
                "full_name": full_name,
                "auth_provider": User.AuthProvider.TELEGRAM,
            },
        )
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(
            {"tokens": build_token_pair(user), "user": UserSerializer(user).data},
            status=status.HTTP_200_OK,
        )


class GoogleLoginURLView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        state = secrets.token_urlsafe(16)
        redirect_uri = request.query_params.get("redirect_uri") or settings.GOOGLE_OAUTH_REDIRECT_URI
        next_url = request.query_params.get("next") or default_frontend_url(request)
        if redirect_uri and not (
            is_allowed_local_frontend_url(redirect_uri) or redirect_uri == settings.GOOGLE_OAUTH_REDIRECT_URI
        ):
            redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
        if next_url and not (
            is_allowed_local_frontend_url(next_url) or next_url.startswith(settings.FRONTEND_URL.rstrip("/"))
        ):
            next_url = default_frontend_url(request)
        request.session[f"google_oauth_redirect_uri:{state}"] = redirect_uri
        request.session[f"google_oauth_next:{state}"] = next_url
        request.session.modified = True
        return Response({"url": build_google_auth_url(state=state, redirect_uri=redirect_uri), "state": state})


class AuthConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        get_token(request._request)
        return Response(
            {
                "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME or "",
                "google_enabled": bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET),
            }
        )


class GoogleCallbackView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def get(self, request):
        code = request.query_params.get("code")
        if not code:
            return Response({"detail": "Missing code"}, status=status.HTTP_400_BAD_REQUEST)

        state = request.query_params.get("state", "")
        redirect_uri = request.session.pop(f"google_oauth_redirect_uri:{state}", settings.GOOGLE_OAUTH_REDIRECT_URI)
        next_url = request.session.pop(f"google_oauth_next:{state}", default_frontend_url(request))
        request.session.modified = True

        payload = fetch_google_userinfo(code, redirect_uri=redirect_uri)
        email = User.objects.normalize_email(payload["email"])
        google_sub = payload["sub"]
        full_name = payload.get("name", "")

        user = User.objects.filter(google_sub=google_sub).first()
        if user is None:
            user = User.objects.filter(email=email).first()

        if user is None:
            user = User.objects.create_user(
                email=email,
                full_name=full_name,
                google_sub=google_sub,
                auth_provider=User.AuthProvider.GOOGLE,
            )
        else:
            update_fields = []
            if user.google_sub != google_sub:
                user.google_sub = google_sub
                update_fields.append("google_sub")
            if full_name and user.full_name != full_name:
                user.full_name = full_name
                update_fields.append("full_name")
            if user.auth_provider != User.AuthProvider.GOOGLE:
                user.auth_provider = User.AuthProvider.GOOGLE
                update_fields.append("auth_provider")
            if update_fields:
                user.save(update_fields=update_fields)

        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        tokens = build_token_pair(user)
        if "text/html" in request.headers.get("Accept", ""):
            frontend_target = next_url or f"{default_frontend_url(request)}/auth/callback"
            separator = "&" if "#" in frontend_target else "#"
            fragment = urlencode(
                {
                    "access": tokens["access"],
                    "refresh": tokens["refresh"],
                }
            )
            return redirect(f"{frontend_target}{separator}{fragment}")
        return Response({"tokens": tokens, "user": UserSerializer(user).data})


class LogoutAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request._request)
        return Response({"detail": "Logged out"}, status=status.HTTP_200_OK)


class MeView(APIView):
    def get(self, request):
        get_token(request._request)
        return Response(UserSerializer(request.user).data)


def auth_page(request):
    return redirect(default_frontend_url(request) if request.user.is_authenticated else f"{default_frontend_url(request)}/auth")


def session_login_view(request):
    if request.method != "POST":
        return redirect("auth-page")

    form = EmailLoginForm(request.POST)
    if not form.is_valid():
        return redirect(f"{default_frontend_url(request)}/auth")

    user = authenticate(
        request,
        username=form.cleaned_data["email"],
        password=form.cleaned_data["password"],
    )
    if user is None:
        form.add_error(None, "Invalid email or password.")
        return redirect(f"{default_frontend_url(request)}/auth")

    login(request, user)
    messages.success(request, "Logged in.")
    return redirect(default_frontend_url(request))


def logout_view(request):
    logout(request)
    return redirect(f"{default_frontend_url(request)}/auth")
