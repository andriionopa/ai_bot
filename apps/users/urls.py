from django.urls import path

from apps.users.views import GoogleCallbackView, GoogleLoginURLView, MeView, TelegramLoginView

urlpatterns = [
    path("telegram/", TelegramLoginView.as_view(), name="telegram-login"),
    path("google/login/", GoogleLoginURLView.as_view(), name="google-login"),
    path("google/callback/", GoogleCallbackView.as_view(), name="google-callback"),
    path("me/", MeView.as_view(), name="me"),
]

