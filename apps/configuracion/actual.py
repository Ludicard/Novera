"""Empresa activa de la petición: cada cuenta pertenece a una empresa y solo ve los datos de esa empresa.

`EmpresaMiddleware` fija la empresa de la cuenta que inició sesión al comienzo de cada petición. Los modelos con
datos de una empresa usan `PorEmpresaManager`, que filtra solo con ella, y `DeEmpresa`, que la asigna al guardar.

Fuera de una petición (migraciones, comandos de consola, admin de un superusuario sin empresa) no hay empresa
activa y el gestor no filtra. Los comandos que escriben datos deben activar una con `usar_empresa`.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

_empresa = ContextVar("novera_empresa", default=None)


def empresa_actual():
    return _empresa.get()


def activar(empresa):
    """Fija la empresa activa y devuelve el token para restaurar la anterior con `desactivar`."""
    return _empresa.set(empresa)


def desactivar(token):
    _empresa.reset(token)


@contextmanager
def usar_empresa(empresa):
    token = activar(empresa)
    try:
        yield empresa
    finally:
        desactivar(token)


class PorEmpresaManager(models.Manager):
    """Gestor que solo devuelve filas de la empresa activa. `campo` es la ruta hasta la empresa."""

    campo = "empresa"

    def get_queryset(self):
        qs = super().get_queryset()
        empresa = empresa_actual()
        if empresa is None:
            return qs
        return qs.filter(**{self.campo: empresa})


def por_empresa(campo, queryset=models.QuerySet):
    """Gestor filtrado por empresa a través de `campo` (p. ej. «cliente__empresa»), con el QuerySet dado."""
    gestor = PorEmpresaManager.from_queryset(queryset)
    return type(f"PorEmpresa_{campo}_{queryset.__name__}", (gestor,), {"campo": campo})()


class SinEmpresaActiva(Exception):
    pass


class DeEmpresa(models.Model):
    """Modelo con datos propios de una empresa: al guardarlo sin empresa toma la activa."""

    empresa = models.ForeignKey("configuracion.Empresa", on_delete=models.PROTECT, related_name="+", editable=False)

    class Meta:
        abstract = True

    def asignar_empresa(self):
        if self.empresa_id is None:
            empresa = empresa_actual()
            if empresa is None:
                raise SinEmpresaActiva(f"No hay empresa activa para guardar {self._meta.verbose_name}.")
            self.empresa = empresa

    def save(self, *args, **kwargs):
        self.asignar_empresa()
        super().save(*args, **kwargs)
