from django.contrib.auth import logout
from django.contrib.sessions.models import Session


class SingleSessionMiddleware:
    """Garante apenas uma sessao ativa por usuario."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            profile = getattr(user, "profile", None)
            if profile and profile.last_session_key:
                current_key = request.session.session_key
                if current_key and current_key != profile.last_session_key:
                    logout(request)
        return self.get_response(request)
