from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.forms import EmailLoginForm
from apps.users.models import User
from apps.users.serializers import TelegramLoginSerializer, UserSerializer
from apps.users.services.google import build_google_auth_url, fetch_google_userinfo
from apps.users.services.tokens import build_token_pair


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
        return Response({"url": build_google_auth_url(state=state), "state": state})


class GoogleCallbackView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def get(self, request):
        code = request.query_params.get("code")
        if not code:
            return Response({"detail": "Missing code"}, status=status.HTTP_400_BAD_REQUEST)

        payload = fetch_google_userinfo(code)
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
        if "text/html" in request.headers.get("Accept", ""):
            return redirect("dashboard-home")
        return Response({"tokens": build_token_pair(user), "user": UserSerializer(user).data})


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


def auth_page(request):
    if request.user.is_authenticated:
        return redirect("dashboard-home")

    form = EmailLoginForm()
    google_error = None
    google_login_url = None
    try:
        google_login_url = build_google_auth_url(state=secrets.token_urlsafe(16))
    except Exception as exc:  # pragma: no cover - config dependent
        google_error = str(exc)

    context = {
        "form": form,
        "google_login_url": google_login_url,
        "google_error": google_error,
        "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
        "backend_url": settings.BACKEND_URL.rstrip("/"),
    }
    return render(request, "auth/login.html", context)


def session_login_view(request):
    if request.method != "POST":
        return redirect("auth-page")

    form = EmailLoginForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "auth/login.html",
            {
                "form": form,
                "google_login_url": None,
                "google_error": None,
                "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
                "backend_url": settings.BACKEND_URL.rstrip("/"),
            },
            status=400,
        )

    user = authenticate(
        request,
        username=form.cleaned_data["email"],
        password=form.cleaned_data["password"],
    )
    if user is None:
        form.add_error(None, "Invalid email or password.")
        return render(
            request,
            "auth/login.html",
            {
                "form": form,
                "google_login_url": None,
                "google_error": None,
                "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
                "backend_url": settings.BACKEND_URL.rstrip("/"),
            },
            status=400,
        )

    login(request, user)
    messages.success(request, "Logged in.")
    return redirect("dashboard-home")


def logout_view(request):
    logout(request)
    return redirect("auth-page")
