"""Testes dos signals."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_out
from django.contrib.sessions.models import Session
from django.test import RequestFactory

from core.models import Profile

pytestmark = pytest.mark.django_db
User = get_user_model()


class TestEnsureProfile:
    def test_profile_created_on_user_creation(self):
        """Signal ensure_profile cria Profile ao criar User."""
        user = User.objects.create_user(
            username="signaluser",
            email="signal@test.com",
            password="x",
        )
        assert Profile.objects.filter(user=user).exists()


class TestEnforceSingleSession:
    def test_sets_last_session_key_on_login(self, client):
        """user_logged_in atualiza last_session_key do profile."""
        user = User.objects.create_user(
            username="sessionuser",
            email="session@test.com",
            password="x",
        )
        client.login(username="sessionuser", password="x")
        profile = Profile.objects.get(user=user)
        assert profile.last_session_key
        assert profile.last_session_key == client.session.session_key

    def test_deletes_old_session_on_new_login(self, client):
        """Ao logar em nova sessão, sessão antiga é removida."""
        user = User.objects.create_user(
            username="multisession",
            email="multi@test.com",
            password="x",
        )
        client.login(username="multisession", password="x")
        old_key = client.session.session_key
        profile = Profile.objects.get(user=user)
        profile.last_session_key = old_key
        profile.save()
        client.logout()
        client.login(username="multisession", password="x")
        new_key = client.session.session_key
        assert not Session.objects.filter(session_key=old_key).exists()
        profile.refresh_from_db()
        assert profile.last_session_key == new_key


class TestClearSingleSession:
    def test_clears_last_session_key_on_logout(self, client):
        """user_logged_out limpa last_session_key."""
        user = User.objects.create_user(
            username="logoutuser",
            email="logout@test.com",
            password="x",
        )
        client.login(username="logoutuser", password="x")
        profile = Profile.objects.get(user=user)
        assert profile.last_session_key
        client.logout()
        profile.refresh_from_db()
        assert profile.last_session_key == ""

    def test_clear_single_session_handles_none_user(self):
        """clear_single_session retorna cedo quando user é None."""
        request = RequestFactory().get("/")
        request.session = {}
        user_logged_out.send(sender=None, request=request, user=None)
