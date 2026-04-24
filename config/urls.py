from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from config.views import (
    AccountAddView,
    AccountStatusView,
    DashboardHomeView,
    ProfileGeneratorView,
    RootRedirectView,
    WarmupView,
    webapp_redirect,
)

urlpatterns = [
    path("", RootRedirectView.as_view(), name="root"),
    path("auth/", include("apps.users.web_urls")),
    path("dashboard/", DashboardHomeView.as_view(), name="dashboard-home"),
    path("dashboard/accounts/", AccountStatusView.as_view(), name="dashboard-accounts"),
    path("dashboard/accounts/add/", AccountAddView.as_view(), name="dashboard-accounts-add"),
    path("dashboard/profiles/", ProfileGeneratorView.as_view(), name="dashboard-profiles"),
    path("dashboard/warmup/", WarmupView.as_view(), name="dashboard-warmup"),
    path("webapp/", webapp_redirect, name="webapp"),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/accounts/", include("apps.telegram_accounts.urls")),
    path("api/v1/profiles/", include("apps.profile_generator.urls")),
    path("api/v1/warmup/", include("apps.warmup.urls")),
    path("api/v1/parser/channels/", include("apps.channel_parser.urls")),
    path("api/v1/parser/messages/", include("apps.message_parser.urls")),
    path("api/v1/parser/comments/", include("apps.comment_parser.urls")),
    path("api/v1/realtime/", include("apps.realtime.urls")),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
]
