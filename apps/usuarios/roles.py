"""Roles de Novera: Administrador, Manager y Técnico.

Cada rol es un grupo de Django (así luego se le pueden colgar permisos). Toda cuenta tiene un rol;
el Administrador puede además elegir con cuál de los tres trabaja en la sesión («ver como»).
"""

from django.contrib.auth.models import Group

ADMINISTRADOR = "administrador"
MANAGER = "manager"
TECNICO = "tecnico"

# clave -> nombre del grupo (en orden de prioridad si alguien tuviera varios)
ROLES = {
    ADMINISTRADOR: "Administrador",
    MANAGER: "Manager",
    TECNICO: "Técnico",
}
CLAVE_POR_GRUPO = {nombre: clave for clave, nombre in ROLES.items()}
SESION_ROL = "rol_activo"


def asegurar_roles():
    for nombre in ROLES.values():
        Group.objects.get_or_create(name=nombre)


def rol_de(usuario):
    """Rol asignado a la cuenta (clave) o None. Un superusuario sin rol pasa a ser Administrador."""
    if not usuario.is_authenticated:
        return None
    nombres = set(usuario.groups.filter(name__in=ROLES.values()).values_list("name", flat=True))
    for clave, nombre in ROLES.items():
        if nombre in nombres:
            return clave
    if usuario.is_superuser:
        asignar_rol(usuario, ADMINISTRADOR)
        return ADMINISTRADOR
    return None


def asignar_rol(usuario, clave):
    """Deja a la cuenta con un único rol."""
    asegurar_roles()
    grupos = {g.name: g for g in Group.objects.filter(name__in=ROLES.values())}
    usuario.groups.remove(*[g for n, g in grupos.items() if n != ROLES[clave]])
    usuario.groups.add(grupos[ROLES[clave]])


def roles_disponibles(rol_asignado):
    """Roles que la cuenta puede usar: el Administrador puede elegir entre los tres."""
    if rol_asignado == ADMINISTRADOR:
        return list(ROLES)
    return [rol_asignado] if rol_asignado else []
