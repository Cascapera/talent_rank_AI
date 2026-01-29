from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.sessions.models import Session
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile

User = get_user_model()


@receiver(post_save, sender=User)
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def enforce_single_session(sender, request, user, **kwargs):
    profile, _ = Profile.objects.get_or_create(user=user)
    # Garante que a sessao existe
    if not request.session.session_key:
        request.session.save()
    current_key = request.session.session_key
    if profile.last_session_key and profile.last_session_key != current_key:
        Session.objects.filter(session_key=profile.last_session_key).delete()
    profile.last_session_key = current_key
    profile.save(update_fields=["last_session_key"])


@receiver(user_logged_out)
def clear_single_session(sender, request, user, **kwargs):
    if not user:
        return
    Profile.objects.filter(user=user).update(last_session_key="")
