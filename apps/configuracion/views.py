from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render

from apps.usuarios.permisos import requiere_rol
from apps.usuarios.roles import ADMINISTRADOR, MANAGER

from .forms import EmpresaForm
from .models import Empresa


@requiere_rol(ADMINISTRADOR)
def configuracion(request):
    empresa = Empresa.actual() or Empresa()
    logo_anterior = empresa.logo.name if empresa.logo else ""
    form = EmpresaForm(request.POST or None, request.FILES or None, instance=empresa)
    if form.is_valid():
        e = form.save(commit=False)
        nuevo_logo = "logo" in request.FILES
        if form.cleaned_data.get("quitar_logo") and not nuevo_logo:
            e.logo = None
        e.actualizado_por = request.user
        e.save()
        # Borra el archivo anterior si se reemplazó o se quitó (no deja copias sueltas en el servidor)
        if logo_anterior and logo_anterior != (e.logo.name if e.logo else ""):
            Empresa._meta.get_field("logo").storage.delete(logo_anterior)
        messages.success(request, "Datos de la empresa guardados. Ya salen en las proformas en PDF.")
        return redirect("configuracion:empresa")
    return render(request, "configuracion/empresa.html", {"form": form, "empresa": empresa if empresa.pk else None})


@requiere_rol(ADMINISTRADOR, MANAGER)
def logo(request):
    """El logo solo se entrega a usuarios con sesión y rol de gestión (no hay URL pública)."""
    e = Empresa.actual()
    if not e or not e.logo:
        raise Http404
    respuesta = FileResponse(e.logo.open("rb"), content_type="image/png")
    respuesta["Cache-Control"] = "private, max-age=300"
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta
