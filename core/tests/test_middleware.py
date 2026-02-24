"""Testes do middleware."""

from unittest.mock import MagicMock, patch

import pytest

from core.middleware import SingleSessionMiddleware

pytestmark = pytest.mark.django_db


class TestSingleSessionMiddleware:
    def test_init_stores_get_response(self):
        get_response = MagicMock()
        mw = SingleSessionMiddleware(get_response)
        assert mw.get_response is get_response

    def test_call_invokes_get_response(self):
        get_response = MagicMock(return_value="response")
        mw = SingleSessionMiddleware(get_response)
        request = MagicMock()
        request.user = None
        result = mw(request)
        assert result == "response"
        get_response.assert_called_once_with(request)

    def test_call_logs_out_when_session_differs(self):
        get_response = MagicMock(return_value="response")
        mw = SingleSessionMiddleware(get_response)
        request = MagicMock()
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.session = MagicMock()
        request.session.session_key = "other_key"
        profile = MagicMock()
        profile.last_session_key = "old_key"
        request.user.profile = profile
        with patch("core.middleware.logout") as mock_logout:
            result = mw(request)
        mock_logout.assert_called_once_with(request)
        assert result == "response"

    def test_call_no_logout_when_same_session(self):
        get_response = MagicMock(return_value="response")
        mw = SingleSessionMiddleware(get_response)
        request = MagicMock()
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.session = MagicMock()
        request.session.session_key = "same_key"
        profile = MagicMock()
        profile.last_session_key = "same_key"
        request.user.profile = profile
        with patch("core.middleware.logout") as mock_logout:
            result = mw(request)
        mock_logout.assert_not_called()
        assert result == "response"
