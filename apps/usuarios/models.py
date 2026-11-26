from django.conf import settings
from django.db import models


class PerfilUsuario(models.Model):
    """A qué empresa pertenece la cuenta. Quien se registra crea la empresa; las cuentas que crea su
    Administrador (o el Manager, en el caso de los técnicos) quedan en la misma empresa."""

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    empresa = models.ForeignKey("configuracion.Empresa", on_delete=models.PROTECT, related_name="miembros")

    class Meta:
        verbose_name = "empresa de la cuenta"
        verbose_name_plural = "empresas de las cuentas"

    def __str__(self):
        return f"{self.usuario} · {self.empresa}"


def empresa_de(usuario):
    """La empresa de la cuenta, o None (cuenta sin empresa o sin sesión)."""
    if not getattr(usuario, "is_authenticated", False):
        return None
    try:
        return usuario.perfil.empresa
    except PerfilUsuario.DoesNotExist:
        return None


def cuentas_de(empresa):
    """Cuentas que pertenecen a la empresa (ninguna si no hay empresa)."""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(perfil__empresa=empresa) if empresa else get_user_model().objects.none()


def unir_a_empresa(usuario, empresa):
    PerfilUsuario.objects.update_or_create(usuario=usuario, defaults={"empresa": empresa})
