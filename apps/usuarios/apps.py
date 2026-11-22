from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsuariosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.usuarios"
    verbose_name = "Usuarios y roles"

    def ready(self):
        from .roles import asegurar_roles

        # Los roles existen siempre que la app arranca con la base migrada (también tras un flush)
        post_migrate.connect(lambda **kwargs: asegurar_roles(), sender=self, weak=False)
