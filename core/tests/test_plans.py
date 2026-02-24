"""Testes do módulo plans."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse

from core.models import Profile
from core.plans import get_user_plan, has_plan_or_more, required_plan

pytestmark = pytest.mark.django_db
User = get_user_model()


def _make_user_with_plan(plan, plan_expires_at=None):
    """Cria usuário com Profile e plano definido."""
    import uuid

    suffix = uuid.uuid4().hex[:8]
    plan_val = plan if isinstance(plan, str) else plan.value
    username = f"plan_{plan_val}_{suffix}"
    User.objects.create_user(
        username=username,
        email=f"{plan_val}_{suffix}@t.com",
        password="x",
    )
    Profile.objects.filter(user__username=username).update(
        plan=plan_val, plan_expires_at=plan_expires_at
    )
    return User.objects.get(username=username)


class TestGetUserPlan:
    def test_none_returns_free(self):
        assert get_user_plan(None) == "FREE"

    def test_anonymous_user_returns_free(self):
        assert get_user_plan(AnonymousUser()) == "FREE"

    def test_authenticated_with_profile_basic(self):
        u = _make_user_with_plan(Profile.Plan.BASIC)
        assert get_user_plan(u) == "BASIC"

    def test_authenticated_with_profile_premium(self):
        u = _make_user_with_plan(Profile.Plan.PREMIUM)
        assert get_user_plan(u) == "PREMIUM"

    def test_expired_plan_returns_free(self):
        u = _make_user_with_plan(
            Profile.Plan.BASIC,
            plan_expires_at=date.today() - timedelta(days=1),
        )
        assert get_user_plan(u) == "FREE"

    def test_future_expiry_returns_plan(self):
        u = _make_user_with_plan(
            Profile.Plan.BASIC,
            plan_expires_at=date.today() + timedelta(days=30),
        )
        assert get_user_plan(u) == "BASIC"

    def test_invalid_plan_returns_free(self):
        u = _make_user_with_plan("INVALID_PLAN")
        assert get_user_plan(u) == "FREE"

    def test_profile_without_plan_expires_at_returns_plan(self):
        u = _make_user_with_plan(Profile.Plan.PREMIUM, plan_expires_at=None)
        assert get_user_plan(u) == "PREMIUM"


class TestHasPlanOrMore:
    def test_basic_has_basic(self):
        u = _make_user_with_plan(Profile.Plan.BASIC)
        assert has_plan_or_more(u, "BASIC") is True

    def test_basic_has_not_premium(self):
        u = _make_user_with_plan(Profile.Plan.BASIC)
        assert has_plan_or_more(u, "PREMIUM") is False

    def test_premium_has_basic(self):
        u = _make_user_with_plan(Profile.Plan.PREMIUM)
        assert has_plan_or_more(u, "BASIC") is True

    def test_free_has_not_basic(self):
        u = _make_user_with_plan(Profile.Plan.FREE)
        assert has_plan_or_more(u, "BASIC") is False

    def test_invalid_min_plan_treated_as_free(self):
        u = _make_user_with_plan(Profile.Plan.PREMIUM)
        assert has_plan_or_more(u, "INVALID") is True


class TestRequiredPlan:
    def _make_request(self, user, is_ajax=False):
        request = MagicMock()
        request.user = user
        request.META = {}
        if is_ajax:
            request.META["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"
        return request

    def test_allows_user_with_sufficient_plan(self):
        @required_plan("BASIC")
        def view(request):
            return HttpResponse("ok")

        u = _make_user_with_plan(Profile.Plan.PREMIUM)
        request = self._make_request(u)
        response = view(request)
        assert response.status_code == 200
        assert response.content == b"ok"

    def test_redirects_unauthenticated_to_login(self):
        @required_plan("BASIC")
        def view(request):
            return HttpResponse("ok")

        request = self._make_request(AnonymousUser())
        response = view(request)
        assert response.status_code == 302
        assert "login" in response.url

    def test_redirects_insufficient_plan_to_dashboard(self):
        @required_plan("PREMIUM")
        def view(request):
            return HttpResponse("ok")

        u = _make_user_with_plan(Profile.Plan.BASIC)
        request = self._make_request(u)
        response = view(request)
        assert response.status_code == 302
        assert "dashboard" in response.url

    def test_ajax_returns_403_for_insufficient_plan(self):
        @required_plan("PREMIUM")
        def view(request):
            return HttpResponse("ok")

        u = _make_user_with_plan(Profile.Plan.BASIC)
        request = self._make_request(u, is_ajax=True)
        response = view(request)
        assert response.status_code == 403
