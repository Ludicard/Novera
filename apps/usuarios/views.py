from functools import wraps
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CuentaForm, RegistroForm
from .models import cuentas_de, unir_a_empresa
from .roles import (
    ADMINISTRADOR, COOKIE_ULTIMO_ROL, DESCRIPCIONES, ROLES, SESION_ROL, administradores_activos, asignar_roles,
    roles_de,
)

Usuario = get_user_model()
NO_VOLVER_A = {"logout", "login", "elegir_rol", "password_change_done"}


def _siguiente(request):
    """URL de retorno segura y que tenga sentido abrir con GET (nunca salir, entrar o el propio selector)."""
    url = request.POST.get("siguiente") or request.GET.get("siguiente") or ""
    if not url or not url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return ""
    try:
        destino = resolve(urlparse(url).path)
    except Resolver404:
        return ""
    if destino.url_name in NO_VOLVER_A:
        return ""
    return url


@login_required
def elegir_rol(request):
    """Pantalla de selección de rol: aparece en cada inicio de sesión, aunque la cuenta tenga un solo rol."""
    disponibles = request.roles
    if not disponibles:
        return render(request, "usuarios/sin_rol.html", status=403)
    siguiente = _siguiente(request)
    error = ""
    if request.method == "POST":
        clave = request.POST.get("rol")
        if clave in disponibles:
            request.session[SESION_ROL] = clave
            respuesta = redirect(siguiente or "inicio")
            respuesta.set_cookie(
                COOKIE_ULTIMO_ROL, clave, max_age=365 * 24 * 3600, httponly=True, samesite="Lax",
                secure=request.is_secure(),
            )
            return respuesta
        error = "Ese rol no está disponible para tu cuenta."

    ultimo = request.COOKIES.get(COOKIE_ULTIMO_ROL)
    if request.rol:
        sugerido = request.rol
    elif ultimo in disponibles:
        sugerido = ultimo
    elif siguiente.startswith("/usuarios/") and ADMINISTRADOR in disponibles:
        sugerido = ADMINISTRADOR
    else:
        sugerido = ADMINISTRADOR if ADMINISTRADOR in disponibles else disponibles[0]
    return render(
        request,
        "usuarios/elegir_rol.html",
        {
            "opciones": [
                {"clave": c, "nombre": ROLES[c], "descripcion": DESCRIPCIONES[c], "sugerido": c == sugerido,
                 "actual": c == request.rol, "ultimo": c == ultimo and not request.rol}
                for c in disponibles
            ],
            "siguiente": siguiente,
            "error": error,
            "es_admin": ADMINISTRADOR in disponibles,
        },
        status=400 if error else 200,
    )


# ---------------------------------------------------------------- registro de una empresa nueva


def registro(request):
    """Crear una empresa: la cuenta que se registra queda como su Administrador y entra directamente."""
    from django.conf import settings
    from django.contrib.auth import login
    from django.http import Http404

    if not settings.NOVERA_REGISTRO_ABIERTO:
        raise Http404
    if request.user.is_authenticated:
        return redirect("inicio")
    form = RegistroForm(request.POST or None)
    if form.is_valid():
        usuario = form.crear()
        login(request, usuario, backend=settings.AUTHENTICATION_BACKENDS[0])
        request.session[SESION_ROL] = ADMINISTRADOR
        messages.success(
            request,
            f"Empresa «{usuario.perfil.empresa.nombre_visible}» creada. Eres su Administrador: crea las cuentas "
            "de tu equipo en Usuarios y completa los datos de la empresa en Configuración.",
        )
        return redirect("inicio")
    return render(request, "registration/registro.html", {"form": form})


# ---------------------------------------------------------------- gestión de cuentas (Administrador)


def solo_administrador(vista):
    @wraps(vista)
    @login_required
    def envoltura(request, *args, **kwargs):
        if request.rol != ADMINISTRADOR:
            messages.error(request, "La gestión de usuarios es solo para el rol Administrador.")
            return redirect("inicio")
        return vista(request, *args, **kwargs)

    return envoltura


def _puede_editar(actor, usuario):
    return actor.is_superuser or not usuario.is_superuser


@solo_administrador
def usuarios_lista(request):
    q = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "activas")
    propias = cuentas_de(request.empresa)
    cuentas = propias.prefetch_related("groups").order_by("-is_active", "first_name", "username")
    if q:
        cuentas = cuentas.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
        )
    if estado == "activas":
        cuentas = cuentas.filter(is_active=True)
    elif estado == "desactivadas":
        cuentas = cuentas.filter(is_active=False)
    pagina = Paginator(cuentas, 50).get_page(request.GET.get("page"))
    for u in pagina:
        u.roles_novera = [(c, ROLES[c]) for c in roles_de(u)]
        u.editable = _puede_editar(request.user, u)
    return render(request, "usuarios/lista.html", {
        "pagina": pagina, "q": q, "estado": estado,
        "conteos": {
            "activas": propias.filter(is_active=True).count(),
            "desactivadas": propias.filter(is_active=False).count(),
        },
    })


@solo_administrador
def usuario_nuevo(request):
    form = CuentaForm(request.POST or None, actor=request.user)
    if form.is_valid():
        u = form.save(commit=False)
        u.set_password(form.cleaned_data["password1"])
        u.save()
        unir_a_empresa(u, request.empresa)  # la cuenta nueva queda en la empresa de quien la crea
        asignar_roles(u, form.cleaned_data["roles"])
        roles = ", ".join(ROLES[c] for c in form.cleaned_data["roles"])
        messages.success(request, f"Cuenta «{u.username}» creada ({roles}). Ya puede iniciar sesión.")
        return redirect("usuarios:lista")
    return render(request, "usuarios/form.html", {"form": form, "titulo": "Nueva cuenta"})


@solo_administrador
def usuario_editar(request, pk):
    usuario = get_object_or_404(cuentas_de(request.empresa), pk=pk)
    if not _puede_editar(request.user, usuario):
        messages.error(request, "Esta cuenta es de un superusuario: solo otro superusuario puede modificarla.")
        return redirect("usuarios:lista")
    form = CuentaForm(request.POST or None, instance=usuario, actor=request.user)
    if form.is_valid():
        u = form.save(commit=False)
        if "activo" in form.cleaned_data and usuario != request.user:
            u.is_active = form.cleaned_data["activo"]
        nueva = form.cleaned_data.get("password1")
        if nueva:
            u.set_password(nueva)
        u.save()
        asignar_roles(u, form.cleaned_data["roles"])
        if nueva and u == request.user:
            update_session_auth_hash(request, u)  # no cerrar mi propia sesión
        texto = f"Cuenta «{u.username}» actualizada"
        texto += " y contraseña cambiada. Compártela de forma segura." if nueva else "."
        messages.success(request, texto)
        return redirect("usuarios:lista")
    return render(request, "usuarios/form.html", {
        "form": form, "cuenta": usuario, "titulo": f"Editar {usuario.get_full_name() or usuario.username}",
        "es_yo": usuario == request.user,
    })


@solo_administrador
@require_POST
def usuario_activar(request, pk):
    usuario = get_object_or_404(cuentas_de(request.empresa), pk=pk)
    if not _puede_editar(request.user, usuario) or usuario == request.user:
        messages.error(request, "No puedes cambiar el estado de esta cuenta.")
        return redirect("usuarios:lista")
    activar = not usuario.is_active
    if not activar and ADMINISTRADOR in roles_de(usuario) and not administradores_activos(request.empresa, excluir=usuario).exists():
        messages.error(request, "Debe quedar al menos un Administrador activo.")
        return redirect("usuarios:lista")
    usuario.is_active = activar
    usuario.save(update_fields=["is_active"])
    messages.success(request, f"Cuenta «{usuario.username}» {'activada' if activar else 'desactivada: ya no puede iniciar sesión'}.")
    return redirect("usuarios:lista")
