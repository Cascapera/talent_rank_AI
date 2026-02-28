"""Testes dos helpers do llm_extractor (sem chamadas à API)."""

import json

import pytest

# Importa funções que não chamam a API
from core.llm_extractor import _extract_json, _normalize_linkedin_url, _normalize_list


class TestNormalizeList:
    def test_none_returns_empty(self):
        assert _normalize_list(None) == []

    def test_empty_list_returns_empty(self):
        assert _normalize_list([]) == []

    def test_list_with_items(self):
        assert _normalize_list(["a", "b", "c"]) == ["a", "b", "c"]

    def test_list_strips_whitespace(self):
        assert _normalize_list(["  a  ", " b "]) == ["a", "b"]

    def test_string_comma_separated(self):
        assert _normalize_list("a, b, c") == ["a", "b", "c"]

    def test_empty_string_returns_empty(self):
        assert _normalize_list("") == []


class TestNormalizeLinkedinUrl:
    def test_empty_returns_empty(self):
        assert _normalize_linkedin_url("") == ""

    def test_adds_https_if_missing(self):
        result = _normalize_linkedin_url("linkedin.com/in/user")
        assert result.startswith("https://")

    def test_keeps_https_if_present(self):
        url = "https://linkedin.com/in/user"
        assert _normalize_linkedin_url(url) == url

    def test_non_linkedin_returns_trimmed(self):
        assert _normalize_linkedin_url("  other.com  ") == "other.com"


class TestExtractJson:
    def test_valid_json_object(self):
        data = _extract_json('{"a": 1, "b": 2}')
        assert data == {"a": 1, "b": 2}

    def test_valid_json_array(self):
        data = _extract_json("[1, 2, 3]")
        assert data == [1, 2, 3]

    def test_extracts_object_from_markdown(self):
        text = '```json\n{"x": 10}\n```'
        data = _extract_json(text)
        assert data == {"x": 10}

    def test_extracts_array_from_text(self):
        text = 'Algum texto [{"a": 1}] mais texto'
        data = _extract_json(text)
        assert data == [{"a": 1}]

    def test_raises_for_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("not json at all {")


class TestGenerateParecer:
    """Testes da função generate_parecer com mock da API Gemini."""

    def test_raises_without_gemini_api_key(self):
        """Levanta RuntimeError quando GEMINI_API_KEY não está definido."""
        from unittest.mock import patch

        from core.llm_extractor import generate_parecer

        job_desc = "Vaga Dev"
        candidate_data = {"name": "João", "summary": "Resumo"}
        with patch("core.llm_extractor.os.getenv", return_value=None):
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                generate_parecer(
                    job_description=job_desc,
                    candidate_data=candidate_data,
                    parecer_type="RESUMIDO",
                    role_title="Dev",
                )

    def test_returns_mocked_response(self):
        """generate_parecer retorna texto da resposta mockada da API."""
        from unittest.mock import MagicMock, patch

        from core.llm_extractor import generate_parecer

        mock_response = MagicMock()
        mock_response.text = "Parecer profissional do candidato."

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        job_desc = "Vaga Arquiteto de Software"
        candidate_data = {
            "name": "Maria",
            "current_title": "Dev Senior",
            "summary": "Experiência em Python",
        }
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("core.llm_extractor.genai.Client", return_value=mock_client):
                result = generate_parecer(
                    job_description=job_desc,
                    candidate_data=candidate_data,
                    parecer_type="RESUMIDO",
                    role_title="Arquiteto",
                )
        assert result == "Parecer profissional do candidato."
        mock_client.models.generate_content.assert_called_once()

    def test_builds_prompt_with_candidate_data(self):
        """Prompt inclui dados do candidato e regras de formato."""
        from unittest.mock import MagicMock, patch

        from core.llm_extractor import generate_parecer

        mock_response = MagicMock()
        mock_response.text = "Parecer."

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        job_desc = "Vaga Python"
        candidate_data = {
            "name": "Carlos",
            "current_title": "Dev",
            "skills": "Python, Django",
        }
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("core.llm_extractor.genai.Client", return_value=mock_client):
                generate_parecer(
                    job_description=job_desc,
                    candidate_data=candidate_data,
                    parecer_type="ROBUSTO",
                    role_title="Dev Python",
                )
        call_kwargs = mock_client.models.generate_content.call_args[1]
        contents = call_kwargs.get("contents", [])
        prompt = contents[-1] if contents and isinstance(contents[-1], str) else ""
        assert "Carlos" in prompt
        assert "Python, Django" in prompt
        assert "4 parágrafos" in prompt or "20 linhas" in prompt
