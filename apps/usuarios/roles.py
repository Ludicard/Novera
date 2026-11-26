"""Roles de Novera: Manager, Administrador y Técnico.

Cada rol es un grupo de Django (así luego se le pueden colgar permisos). Una cuenta tiene acceso a uno o
varios roles; quien tiene Administrador puede usar los tres. Al iniciar sesión siempre se elige con qué rol
se trabaja (pantalla de selección), y ese rol activo vive en la sesión.
"""

from django.contrib.auth.models import Group

MANAGER = "manager"
ADMINISTRADOR = "administrador"
TECNICO = "tecnico"

# clave -> nombre del grupo, en el orden en que se muestran
ROLES = {
    MANAGER: "Manager",
    ADMINISTRADOR: "Administrador",
    TECNICO: "Técnico",
}
DESCRIPCIONES = {
    MANAGER: "Clientes, técnicos, equipos, proformas y órdenes de trabajo",
    ADMINISTRADOR: "Proformas, órdenes, facturas, pagos y datos financieros",
    TECNICO: "Mis órdenes de trabajo e informes",
}
SESION_ROL = "rol_activo"
COOKIE_ULTIMO_ROL = "novera_rol"
CLAVE_POR_NOMBRE = {nombre: clave for clave, nombre in ROLES.items()}


def asegurar_roles():
    for nombre in ROLES.values():
        Group.objects.get_or_create(name=nombre)


def roles_de(usuario):
    """Roles asignados a la cuenta (claves, en orden). Un superusuario siempre cuenta como Administrador.

    Solo lee: nunca escribe en la base de datos (se llama en cada petición).
    """
    if not usuario.is_authenticated:
        return []
    nombres = {g.name for g in usuario.groups.all() if g.name in CLAVE_POR_NOMBRE}
    roles = [clave for clave, nombre in ROLES.items() if nombre in nombres]
    if usuario.is_superuser and ADMINISTRADOR not in roles:
        roles = [c for c in ROLES if c in roles or c == ADMINISTRADOR]
    return roles


def es_administrador(usuario):
    return ADMINISTRADOR in roles_de(usuario)


def administradores_activos(empresa, excluir=None):
    """Cuentas activas de la empresa con acceso de Administrador (por rol o por ser superusuario)."""
    from django.db.models import Q

    from .models import cuentas_de

    qs = cuentas_de(empresa).filter(is_active=True).filter(
        Q(groups__name=ROLES[ADMINISTRADOR]) | Q(is_superuser=True)
    )
    if excluir is not None:
        qs = qs.exclude(pk=excluir.pk)
    return qs.distinct()


def roles_disponibles(asignados):
    """Roles con los que la cuenta puede entrar: Administrador da acceso a los tres."""
    if ADMINISTRADOR in asignados:
        return list(ROLES)
    return [clave for clave in ROLES if clave in asignados]


def asignar_roles(usuario, claves):
    """Deja a la cuenta exactamente con esos roles."""
    asegurar_roles()
    grupos = {g.name: g for g in Group.objects.filter(name__in=ROLES.values())}
    quiero = {ROLES[c] for c in claves}
    usuario.groups.remove(*[g for n, g in grupos.items() if n not in quiero])
    usuario.groups.add(*[grupos[n] for n in quiero])
