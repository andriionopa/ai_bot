from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.warmup.views import (
    WarmupActionViewSet,
    WarmupOverviewViewSet,
    WarmupPlanViewSet,
    WarmupPolicyViewSet,
    WarmupTargetViewSet,
)

router = DefaultRouter()
router.register("policies", WarmupPolicyViewSet, basename="warmup-policy")
router.register("targets", WarmupTargetViewSet, basename="warmup-target")
router.register("plans", WarmupPlanViewSet, basename="warmup-plan")
router.register("actions", WarmupActionViewSet, basename="warmup-action")

warmup_overview = WarmupOverviewViewSet.as_view({"get": "list"})
warmup_policy_add = WarmupPolicyViewSet.as_view({"post": "create"})
warmup_target_add = WarmupTargetViewSet.as_view({"post": "create"})
warmup_target_bulk_import = WarmupTargetViewSet.as_view({"post": "bulk_import"})
warmup_plan_add = WarmupPlanViewSet.as_view({"post": "create"})
warmup_plan_start = WarmupPlanViewSet.as_view({"post": "start"})
warmup_plan_pause = WarmupPlanViewSet.as_view({"post": "pause"})
warmup_plan_stop = WarmupPlanViewSet.as_view({"post": "stop"})
warmup_action_run_due = WarmupActionViewSet.as_view({"post": "run_due"})
warmup_action_clear = WarmupActionViewSet.as_view({"post": "clear"})

urlpatterns = [
    path("overview/", warmup_overview, name="warmup-overview"),
    path("policies/add/", warmup_policy_add, name="warmup-policy-add"),
    path("targets/add/", warmup_target_add, name="warmup-target-add"),
    path("targets/bulk-import/", warmup_target_bulk_import, name="warmup-target-bulk-import"),
    path("plans/add/", warmup_plan_add, name="warmup-plan-add"),
    path("plans/<int:pk>/start/", warmup_plan_start, name="warmup-plan-start"),
    path("plans/<int:pk>/pause/", warmup_plan_pause, name="warmup-plan-pause"),
    path("plans/<int:pk>/stop/", warmup_plan_stop, name="warmup-plan-stop"),
    path("actions/run-due/", warmup_action_run_due, name="warmup-action-run-due"),
    path("actions/clear/", warmup_action_clear, name="warmup-action-clear"),
] + router.urls
