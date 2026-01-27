"""
Permissões por plano de assinatura: Free, Basic, Premium.
- Free: só dashboard (e home, login, logout).
- Basic: vagas + banco de talentos.
- Premium: vagas + banco de talentos + relatórios.

O plano é editado manualmente no admin (futuramente via assinatura/pagamento).
Se plan_expires_at estiver preenchido e for anterior a hoje, o acesso é bloqueado (tratado como FREE).
"""
from functools import wraps
from datetime import date

from django.contrib import messages
from django.shortcuts import redirect


# Ordem para comparação: Free < Basic < Premium
PLAN_ORDER = {
    'FREE': 0,
    'BASIC': 1,
    'PREMIUM': 2,
}


def get_user_plan(user):
    """
    Retorna o plano do usuário ('FREE', 'BASIC' ou 'PREMIUM').
    Sem perfil ou plano inválido = FREE.
    Se plan_expires_at estiver preenchido e for anterior a hoje, retorna FREE (plano vencido).
    """
    if not user or not user.is_authenticated:
        return 'FREE'
    try:
        profile = user.profile
        plan = (profile.plan or 'FREE').upper()
        if plan not in PLAN_ORDER:
            return 'FREE'
        # Plano vencido: data de vencimento preenchida e já passou
        if getattr(profile, 'plan_expires_at', None):
            if profile.plan_expires_at < date.today():
                return 'FREE'
        return plan
    except Exception:
        return 'FREE'


def has_plan_or_more(user, min_plan):
    """True se o usuário tem pelo menos o plano min_plan e o plano não está vencido."""
    return PLAN_ORDER.get(get_user_plan(user), 0) >= PLAN_ORDER.get(min_plan.upper(), 0)


def required_plan(min_plan):
    """
    Decorator: exige que o usuário esteja logado e tenha pelo menos o plano min_plan.
    Use junto com @login_required (que deve ficar acima, para rodar primeiro).
    Redireciona para o dashboard com mensagem se o plano for insuficiente.
    Para requisições AJAX/JSON retorna 403.
    """
    min_plan = min_plan.upper()
    if min_plan not in PLAN_ORDER:
        min_plan = 'FREE'

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            from django.http import JsonResponse
            is_ajax = (
                request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
                or 'application/json' in (request.META.get('HTTP_ACCEPT') or '')
            )
            if not request.user.is_authenticated:
                if is_ajax:
                    return JsonResponse({'error': 'Não autorizado.', 'reason': 'login'}, status=403)
                return redirect('login')
            if not has_plan_or_more(request.user, min_plan):
                plan_label = dict([('FREE', 'Free'), ('BASIC', 'Basic'), ('PREMIUM', 'Premium')]).get(min_plan, min_plan)
                try:
                    profile = getattr(request.user, 'profile', None)
                    if profile and getattr(profile, 'plan_expires_at', None) and profile.plan_expires_at < date.today():
                        msg = 'Seu plano venceu. Renove sua assinatura para continuar acessando.'
                    else:
                        msg = f'Seu plano atual não inclui acesso a esta funcionalidade. É necessário plano {plan_label} ou superior.'
                except Exception:
                    msg = f'Seu plano atual não inclui acesso a esta funcionalidade. É necessário plano {plan_label} ou superior.'
                messages.warning(request, msg)
                if is_ajax:
                    return JsonResponse({'error': msg, 'reason': 'plan'}, status=403)
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
