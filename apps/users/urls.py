from django.urls import path

from apps.users.views import AuthConfigView, GoogleCallbackView, GoogleLoginURLView, LogoutAPIView, MeView, TelegramLoginView

urlpatterns = [
    path("config/", AuthConfigView.as_view(), name="auth-config"),
    path("telegram/", TelegramLoginView.as_view(), name="telegram-login"),
    path("google/login/", GoogleLoginURLView.as_view(), name="google-login"),
    path("google/callback/", GoogleCallbackView.as_view(), name="google-callback"),
    path("logout/", LogoutAPIView.as_view(), name="api-logout"),
    path("me/", MeView.as_view(), name="me"),
]
