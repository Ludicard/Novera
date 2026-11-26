from django.conf import settings

from .models import NOMBRE_POR_DEFECTO, tema_aplicacion


def tema(request):
    """Empresa de la cuenta (nombre y logo de la barra) y color de la aplicación elegido en Configuración."""
    empresa = getattr(request, "empresa", None)
    datos = {
        "empresa_actual": empresa,
        "empresa_nombre": empresa.nombre_visible if empresa else NOMBRE_POR_DEFECTO,
        "registro_abierto": settings.NOVERA_REGISTRO_ABIERTO,
    }
    try:
        datos["tema_app"] = tema_aplicacion(empresa) if empresa else None
    except Exception:  # p. ej. antes de migrar: la app sigue en azul
        datos["tema_app"] = None
    return datos
