from django.conf import settings
from django.shortcuts import redirect
from django.views.generic import RedirectView


def frontend_url(path: str = "") -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/{path.lstrip('/')}"


class RootRedirectView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return frontend_url("" if self.request.user.is_authenticated else "auth")


class DashboardHomeView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return frontend_url("")


class AccountStatusView(DashboardHomeView):
    pass


class AccountAddView(DashboardHomeView):
    pass


class ProfileGeneratorView(DashboardHomeView):
    pass


class WarmupView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return frontend_url("warmup")


def webapp_redirect(request):
    return redirect(frontend_url("" if request.user.is_authenticated else "auth"))
