from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.telegram_accounts.views import AccountRoleTemplateViewSet, ProxyViewSet, TelegramAccountViewSet

router = DefaultRouter()
router.register("proxies", ProxyViewSet, basename="proxy")
router.register("role-templates", AccountRoleTemplateViewSet, basename="account-role-template")
router.register("telegram-accounts", TelegramAccountViewSet, basename="telegram-account")

account_overview = TelegramAccountViewSet.as_view({"get": "overview"})
account_add = TelegramAccountViewSet.as_view({"post": "add"})
account_detach = TelegramAccountViewSet.as_view({"post": "bulk_detach"})
account_cleanup_stale = TelegramAccountViewSet.as_view({"post": "cleanup_stale"})
account_health = TelegramAccountViewSet.as_view({"get": "health"})
account_complete_auth = TelegramAccountViewSet.as_view({"post": "complete_auth"})
account_resend_code = TelegramAccountViewSet.as_view({"post": "resend_code"})
account_assign_proxy = TelegramAccountViewSet.as_view({"post": "assign_proxy"})
account_runtime_events = TelegramAccountViewSet.as_view({"post": "runtime_events"})
proxy_add = ProxyViewSet.as_view({"post": "create"})
proxy_test = ProxyViewSet.as_view({"get": "test", "post": "test"})

urlpatterns = [
    path("overview/", account_overview, name="account-overview"),
    path("add/", account_add, name="account-add"),
    path("detach/", account_detach, name="account-detach"),
    path("cleanup-stale/", account_cleanup_stale, name="account-cleanup-stale"),
    path("<int:pk>/health/", account_health, name="account-health"),
    path("<int:pk>/complete-auth/", account_complete_auth, name="account-complete-auth"),
    path("<int:pk>/resend-code/", account_resend_code, name="account-resend-code"),
    path("<int:pk>/proxy/", account_assign_proxy, name="account-assign-proxy"),
    path("<int:pk>/runtime-events/", account_runtime_events, name="account-runtime-events"),
    path("proxies/add/", proxy_add, name="proxy-add"),
    path("proxies/<int:pk>/test/", proxy_test, name="proxy-test"),
] + router.urls
