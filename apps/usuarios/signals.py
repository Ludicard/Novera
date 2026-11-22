from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .roles import SESION_ROL


@receiver(user_logged_in)
def olvidar_rol_al_entrar(sender, request, user, **kwargs):
    """Cada inicio de sesión vuelve a pasar por la pantalla de selección de rol."""
    request.session.pop(SESION_ROL, None)
