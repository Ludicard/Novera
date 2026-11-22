from .roles import ROLES, roles_disponibles


def rol(request):
    asignado = getattr(request, "rol_asignado", None)
    actual = getattr(request, "rol", None)
    return {
        "rol": actual,
        "rol_nombre": ROLES.get(actual, ""),
        "rol_asignado": asignado,
        "roles_elegibles": [(c, ROLES[c]) for c in roles_disponibles(asignado)],
    }
