"""Testes dos formulários."""

import pytest
from django.contrib.auth import get_user_model

from core.forms import CandidateForm, JobForm, SignupForm, _clean_cpf
from core.models import Profile

pytestmark = pytest.mark.django_db
User = get_user_model()


class TestCleanCpf:
    def test_returns_digits_only(self):
        assert _clean_cpf("123.456.789-00") == "12345678900"

    def test_raises_for_invalid_length(self):
        from django.forms import ValidationError

        with pytest.raises(ValidationError):
            _clean_cpf("1234567890")  # 10 dígitos

    def test_empty_returns_empty(self):
        assert _clean_cpf("") == ""


class TestSignupForm:
    def test_valid_data_creates_user(self):
        form = SignupForm(
            data={
                "username": "user1",
                "email": "u1@test.com",
                "first_name": "First",
                "last_name": "Last",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            }
        )
        assert form.is_valid()
        user = form.save()
        assert user.username == "user1"
        assert user.email == "u1@test.com"

    def test_duplicate_email_invalid(self, user):
        form = SignupForm(
            data={
                "username": "other",
                "email": "test@example.com",
                "first_name": "A",
                "last_name": "B",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            }
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_save_updates_profile_with_phone_and_cpf(self):
        """SignupForm.save(commit=True) atualiza Profile com phone e cpf."""
        form = SignupForm(
            data={
                "username": "profileuser",
                "email": "profile@test.com",
                "first_name": "F",
                "last_name": "L",
                "phone": "11999998888",
                "cpf": "123.456.789-00",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            }
        )
        assert form.is_valid()
        user = form.save(commit=True)
        profile = Profile.objects.get(user=user)
        assert profile.phone == "11999998888"
        assert profile.cpf == "12345678900"

    def test_save_commit_false_does_not_update_profile(self):
        """SignupForm.save(commit=False) não persiste Profile."""
        form = SignupForm(
            data={
                "username": "nocommit",
                "email": "nocommit@test.com",
                "first_name": "F",
                "last_name": "L",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            }
        )
        assert form.is_valid()
        user = form.save(commit=False)
        assert user.pk is None
        user.save()
        assert Profile.objects.filter(user=user).exists()


class TestJobForm:
    def test_job_form_has_expected_fields(self):
        expected = {
            "title",
            "summary",
            "department",
            "seniority",
            "location",
            "stack",
            "must_have",
            "nice_to_have",
        }
        form_fields = set(JobForm.Meta.fields)
        assert expected.issubset(form_fields)


class TestCandidateForm:
    def test_candidate_form_has_linkedin_required(self):
        form = CandidateForm()
        assert "linkedin_url" in form.fields
