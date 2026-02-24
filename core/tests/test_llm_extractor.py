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
