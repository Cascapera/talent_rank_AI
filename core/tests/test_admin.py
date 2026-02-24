"""Testes do admin."""

import pytest
from django.contrib.admin.sites import site

from core.admin import CandidateAdmin
from core.models import Candidate

pytestmark = pytest.mark.django_db


class TestCandidateAdmin:
    def test_has_resume_pdf_returns_true_when_pdf_exists(self, user):
        """has_resume_pdf retorna True quando candidato tem PDF."""
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        candidate.resume_pdf = "resumes/1/abc123.pdf"
        candidate.save()
        admin = CandidateAdmin(Candidate, site)
        assert admin.has_resume_pdf(candidate) is True

    def test_has_resume_pdf_returns_false_when_no_pdf(self, user):
        """has_resume_pdf retorna False quando candidato não tem PDF."""
        candidate = Candidate.objects.create(
            user=user,
            name="Maria",
            linkedin_url="https://linkedin.com/in/maria",
        )
        admin = CandidateAdmin(Candidate, site)
        assert admin.has_resume_pdf(candidate) is False
