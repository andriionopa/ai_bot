from django.urls import path

from apps.users.views import auth_page, logout_view, session_login_view

urlpatterns = [
    path("", auth_page, name="auth-page"),
    path("login/", session_login_view, name="session-login"),
    path("logout/", logout_view, name="logout"),
]

