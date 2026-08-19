"""Testes da rota autenticada de download de currículo (R-23).

Antes deste item o PDF saía do Nginx direto de `/media/`, sem passar pelo Django: quem
tivesse a URL baixava, logado ou não. Aqui o que se fixa é **quem consegue baixar**, e
que a permissão é conferida antes de qualquer byte sair.

O `X-Accel-Redirect` é testado com o setting ligado à mão: em produção quem lê o disco é
o Nginx, e o Django devolve resposta vazia com o caminho interno. Na suíte e no
`runserver` vale o outro caminho, o `FileResponse`.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.urls import reverse

from core.models import Candidate, Profile

pytestmark = pytest.mark.django_db

User = get_user_model()

PDF_BYTES = b"%PDF-1.4 conteudo falso de curriculo"


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


def make_candidate(owner, name="Fulano de Tal", with_pdf=True):
    candidate = Candidate.objects.create(
        user=owner,
        name=name,
        linkedin_url=f"https://linkedin.com/in/{name.replace(' ', '-').lower()}",
    )
    if with_pdf:
        candidate.resume_pdf.save("curriculo.pdf", ContentFile(PDF_BYTES), save=True)
    return candidate


def make_user(username, plan=Profile.Plan.BASIC):
    u = User.objects.create_user(username=username, password="testpass123")
    Profile.objects.update_or_create(user=u, defaults={"plan": plan})
    return u


def body_of(response):
    if hasattr(response, "streaming_content"):
        return b"".join(response.streaming_content)
    return response.content


def test_anonimo_vai_para_o_login(client, user):
    candidate = make_candidate(user)

    response = client.get(reverse("resume_download", args=[candidate.id]))

    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_dono_baixa_o_proprio_curriculo(client_logged, user):
    candidate = make_candidate(user)

    response = client_logged.get(reverse("resume_download", args=[candidate.id]))

    assert response.status_code == 200
    assert body_of(response) == PDF_BYTES
    assert response["Content-Type"] == "application/pdf"
    # Anexo, não preview: o motivo do item é ela recuperar o arquivo, não só olhar.
    assert response["Content-Disposition"].startswith("attachment")


def test_nome_do_arquivo_vem_do_candidato_nao_do_uuid_em_disco(client_logged, user):
    candidate = make_candidate(user, name="Maria da Silva")

    response = client_logged.get(reverse("resume_download", args=[candidate.id]))

    assert "maria-da-silva.pdf" in response["Content-Disposition"]
    # O nome em disco é `resumes/<user_id>/<uuid>.pdf` e não deve vazar para o download.
    assert ".pdf" in candidate.resume_pdf.name
    assert "maria" not in candidate.resume_pdf.name


def test_outra_conta_no_plano_basic_recebe_404(client, user):
    candidate = make_candidate(user)
    intruso = make_user("intruso")
    client.force_login(intruso)

    response = client.get(reverse("resume_download", args=[candidate.id]))

    # 404 e não 403: 403 confirmaria que o candidato existe.
    assert response.status_code == 404


def test_premium_baixa_do_pool_compartilhado(client, user):
    """Decisão registrada: a visibilidade **espelha a da listagem**.

    No PREMIUM o pool é comunitário (`Candidate.objects.all()` em `talent_pool`), e uma
    checagem mais estreita aqui faria o botão dar 404 numa linha que a tela mostra.
    Se essa regra do pool mudar, este teste é o que precisa mudar junto.
    """
    candidate = make_candidate(user)
    premium = make_user("premium", plan=Profile.Plan.PREMIUM)
    client.force_login(premium)

    response = client.get(reverse("resume_download", args=[candidate.id]))

    assert response.status_code == 200
    assert body_of(response) == PDF_BYTES


def test_candidato_sem_pdf_da_404(client_logged, user):
    candidate = make_candidate(user, with_pdf=False)

    response = client_logged.get(reverse("resume_download", args=[candidate.id]))

    assert response.status_code == 404


def test_candidato_inexistente_da_404(client_logged, user):
    response = client_logged.get(reverse("resume_download", args=[99999]))

    assert response.status_code == 404


def test_com_x_accel_o_django_nao_manda_o_arquivo(client_logged, user, settings):
    settings.USE_X_ACCEL_REDIRECT = True
    settings.PROTECTED_MEDIA_PREFIX = "/protected-media/"
    candidate = make_candidate(user)

    response = client_logged.get(reverse("resume_download", args=[candidate.id]))

    assert response.status_code == 200
    # O corpo é vazio de propósito: quem preenche é o Nginx. Se o PDF aparecesse aqui,
    # ele estaria atravessando o worker do gunicorn — o oposto do que o item quer.
    assert response.content == b""
    assert response["X-Accel-Redirect"] == "/protected-media/" + candidate.resume_pdf.name
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("attachment")


def test_x_accel_nao_dispensa_a_checagem_de_permissao(client, user, settings):
    settings.USE_X_ACCEL_REDIRECT = True
    candidate = make_candidate(user)
    intruso = make_user("intruso2")
    client.force_login(intruso)

    response = client.get(reverse("resume_download", args=[candidate.id]))

    assert response.status_code == 404
    assert "X-Accel-Redirect" not in response
