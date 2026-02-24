"""Testes dos helpers do pdf_extractor (sem DB)."""

from core.pdf_extractor import (
    _clean_lines,
    _find_linkedin_url,
    _fix_mojibake,
    _normalize_search_term,
)


class TestNormalizeSearchTerm:
    def test_removes_accents(self):
        assert _normalize_search_term("Sênior") == "senior"

    def test_lowercase(self):
        assert _normalize_search_term("Python") == "python"

    def test_empty(self):
        assert _normalize_search_term("") == ""


class TestFindLinkedinUrl:
    def test_finds_https_url(self):
        text = "Perfil: https://linkedin.com/in/john-doe"
        assert "linkedin.com/in/john-doe" in _find_linkedin_url(text)

    def test_adds_https_when_missing(self):
        text = "linkedin.com/in/jane"
        assert _find_linkedin_url(text).startswith("https://")

    def test_returns_empty_when_not_found(self):
        assert _find_linkedin_url("No linkedin here") == ""


class TestCleanLines:
    def test_strips_lines(self):
        lines = _clean_lines("  a  \n  b  ")
        assert lines == ["a", "b"]

    def test_skips_page_headers(self):
        lines = _clean_lines("Page 1 of 2\nContent")
        assert "Content" in lines

    def test_removes_bullet_prefix(self):
        lines = _clean_lines("- item")
        assert lines and lines[0] == "item"


class TestFixMojibake:
    def test_returns_text_unchanged_when_clean(self):
        assert _fix_mojibake("hello") == "hello"
