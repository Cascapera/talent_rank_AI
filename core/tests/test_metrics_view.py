"""Testes do endpoint /metrics (R-22).

O primeiro teste é characterization: registra o comportamento de hoje, em que o
endpoint responde 200 para qualquer um. Ele continua valendo depois do R-22 porque
essa é a metade "expand" do expand-contract — sem `METRICS_TOKEN` no ambiente, o
endpoint segue aberto e o scraper existente não quebra no deploy.
"""

import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


class TestMetricsSemToken:
    """METRICS_TOKEN vazio = comportamento anterior ao R-22, preservado."""

    @override_settings(METRICS_TOKEN="")
    def test_responde_200_para_anonimo(self, client):
        response = client.get(reverse("metrics"))
        assert response.status_code == 200

    @override_settings(METRICS_TOKEN="")
    def test_devolve_formato_prometheus(self, client):
        response = client.get(reverse("metrics"))
        assert response["Content-Type"].startswith("text/plain")
        assert b"vacancy_candidate_imports_total" in response.content


class TestMetricsComToken:
    """Com METRICS_TOKEN configurado o endpoint fecha."""

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_sem_header_da_401(self, client):
        response = client.get(reverse("metrics"))
        assert response.status_code == 401
        assert b"vacancy_candidate_imports_total" not in response.content

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_token_errado_da_401(self, client):
        response = client.get(reverse("metrics"), headers={"x-metrics-token": "errado"})
        assert response.status_code == 401

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_header_x_metrics_token_da_200(self, client):
        response = client.get(reverse("metrics"), headers={"x-metrics-token": "s3cr3t"})
        assert response.status_code == 200
        assert b"vacancy_candidate_imports_total" in response.content

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_authorization_bearer_da_200(self, client):
        """O Prometheus manda Bearer nativamente (scrape_config: authorization)."""
        response = client.get(reverse("metrics"), headers={"authorization": "Bearer s3cr3t"})
        assert response.status_code == 200

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_authorization_bearer_errado_da_401(self, client):
        response = client.get(reverse("metrics"), headers={"authorization": "Bearer errado"})
        assert response.status_code == 401

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_prefixo_bearer_e_case_insensitive(self, client):
        response = client.get(reverse("metrics"), headers={"authorization": "bearer s3cr3t"})
        assert response.status_code == 200

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_token_nao_ascii_da_401_e_nao_500(self, client):
        """`hmac.compare_digest` em str aceita so ASCII — em bytes nao levanta."""
        response = client.get(reverse("metrics"), headers={"x-metrics-token": "senhá"})
        assert response.status_code == 401

    @override_settings(METRICS_TOKEN="s3cr3t")
    def test_401_nao_exige_login_na_tela(self, client):
        """Scraper não segue redirect de login: a resposta tem que ser 401, não 302."""
        response = client.get(reverse("metrics"))
        assert response.status_code == 401
        assert "Location" not in response
