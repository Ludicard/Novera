from django import test
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save

from apps.configuracion.actual import activar, desactivar
from apps.configuracion.models import Empresa
from apps.usuarios.models import empresa_de, unir_a_empresa
from apps.usuarios.roles import SESION_ROL, asignar_roles


def _unir_cuenta_nueva(sender, instance, created, **kwargs):
    from apps.configuracion.actual import empresa_actual

    if created and empresa_actual() is not None and empresa_de(instance) is None:
        unir_a_empresa(instance, empresa_actual())


class TestCase(test.TestCase):
    """TestCase con una empresa activa (`cls.empresa`, con sus formas de pago iniciales): los datos que crean las
    pruebas quedan en ella, y también las cuentas nuevas, salvo con `unir_cuentas_nuevas = False` (para probar
    que el código de la app une las cuentas a su empresa)."""

    unir_cuentas_nuevas = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from apps.trabajos.models import FormaPago

        cls.empresa = Empresa.objects.create(nombre="Empresa de pruebas")
        FormaPago.crear_iniciales(cls.empresa)
        cls._token_empresa = activar(cls.empresa)
        if cls.unir_cuentas_nuevas:
            post_save.connect(_unir_cuenta_nueva, sender=get_user_model(), dispatch_uid="pruebas_unir_cuenta")

    @classmethod
    def tearDownClass(cls):
        post_save.disconnect(sender=get_user_model(), dispatch_uid="pruebas_unir_cuenta")
        desactivar(cls._token_empresa)
        super().tearDownClass()


def entrar_como(client, usuario, rol, roles=None, empresa=None):
    """Inicia sesión y deja elegido `rol` (asignándole a la cuenta `roles` o solo ese rol).

    Si la cuenta aún no tiene empresa, la une a `empresa` (o a la empresa activa de la prueba)."""
    from apps.configuracion.actual import empresa_actual

    if empresa is not None or empresa_de(usuario) is None:
        unir_a_empresa(usuario, empresa or empresa_actual())
        usuario.refresh_from_db()
    asignar_roles(usuario, roles or [rol])
    client.force_login(usuario)
    sesion = client.session
    sesion[SESION_ROL] = rol
    sesion.save()
