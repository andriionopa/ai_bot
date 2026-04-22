from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import RedirectView, TemplateView


class RootRedirectView(RedirectView):
    pattern_name = "auth-page"

    def get_redirect_url(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return "/dashboard/"
        return super().get_redirect_url(*args, **kwargs)


class DashboardContextMixin(LoginRequiredMixin):
    login_url = "/auth/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["websocket_url"] = "/ws/logs/"
        context["accounts_overview_url"] = "/api/v1/accounts/overview/"
        context["account_add_url"] = "/api/v1/accounts/add/"
        context["account_detach_url"] = "/api/v1/accounts/detach/"
        context["account_cleanup_stale_url"] = "/api/v1/accounts/cleanup-stale/"
        context["proxy_add_url"] = "/api/v1/accounts/proxies/add/"
        context["profile_drafts_url"] = "/api/v1/profiles/drafts/"
        context["warmup_overview_url"] = "/api/v1/warmup/overview/"
        context["warmup_policy_add_url"] = "/api/v1/warmup/policies/add/"
        context["warmup_target_add_url"] = "/api/v1/warmup/targets/add/"
        context["warmup_target_bulk_import_url"] = "/api/v1/warmup/targets/bulk-import/"
        context["warmup_plan_add_url"] = "/api/v1/warmup/plans/add/"
        context["warmup_action_run_due_url"] = "/api/v1/warmup/actions/run-due/"
        context["warmup_action_clear_url"] = "/api/v1/warmup/actions/clear/"
        context["dashboard_home_url"] = "/dashboard/"
        context["dashboard_accounts_url"] = "/dashboard/accounts/"
        context["dashboard_accounts_add_url"] = "/dashboard/accounts/add/"
        context["dashboard_profiles_url"] = "/dashboard/profiles/"
        context["dashboard_warmup_url"] = "/dashboard/warmup/"
        return context


class DashboardHomeView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/index.html"


class AccountStatusView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/accounts_status.html"


class AccountAddView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/accounts_add.html"


class ProfileGeneratorView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/profile_generator.html"


class WarmupView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/warmup.html"


def webapp_redirect(request):
    if request.user.is_authenticated:
        return redirect("dashboard-home")
    return redirect("auth-page")
