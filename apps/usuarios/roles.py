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
    MANAGER: "Seguimiento de cobros, clientes e indicadores",
    ADMINISTRADOR: "Control total: facturas, usuarios e importaciones",
    TECNICO: "Trabajo de campo y servicios asignados",
}
SESION_ROL = "rol_activo"


def asegurar_roles():
    for nombre in ROLES.values():
        Group.objects.get_or_create(name=nombre)


def roles_de(usuario):
    """Roles asignados a la cuenta (claves, en orden). Un superusuario sin roles pasa a ser Administrador."""
    if not usuario.is_authenticated:
        return []
    nombres = set(usuario.groups.filter(name__in=ROLES.values()).values_list("name", flat=True))
    roles = [clave for clave, nombre in ROLES.items() if nombre in nombres]
    if not roles and usuario.is_superuser:
        asignar_roles(usuario, [ADMINISTRADOR])
        roles = [ADMINISTRADOR]
    return roles


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


def agregar_rol(usuario, clave):
    asignar_roles(usuario, set(roles_de(usuario)) | {clave})


def quitar_rol(usuario, clave):
    asignar_roles(usuario, set(roles_de(usuario)) - {clave})
