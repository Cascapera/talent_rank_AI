"""Configuração global do pytest para o projeto Django."""

import pytest
from django.contrib.auth import get_user_model

from core.models import Profile

User = get_user_model()


@pytest.fixture
def user(db):
    """Usuário de teste com plano BASIC."""
    u = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
    )
    Profile.objects.update_or_create(user=u, defaults={"plan": Profile.Plan.BASIC})
    return u


@pytest.fixture
def client_logged(client, user):
    """Client autenticado."""
    client.force_login(user)
    return client
