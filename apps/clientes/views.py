from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.facturas.models import Factura
from apps.usuarios.permisos import requiere_rol
from apps.usuarios.roles import ADMINISTRADOR, MANAGER

from .forms import ClienteForm, ClienteRapidoForm, EquipoForm
from .models import Cliente, Equipo


@login_required
def lista(request):
    q = request.GET.get("q", "").strip()
    clientes = Cliente.objects.con_saldos().annotate(
        num_facturas=Count("facturas", distinct=True), num_equipos=Count("equipos", distinct=True)
    )
    if q:
        clientes = clientes.filter(Q(nombre__icontains=q) | Q(identificacion__icontains=q))
    if request.GET.get("con_saldo"):
        clientes = clientes.filter(saldo__gt=0)
    orden = request.GET.get("orden", "nombre")
    clientes = clientes.order_by("-saldo", "nombre") if orden == "saldo" else clientes.order_by("nombre")
    pagina = Paginator(clientes, 50).get_page(request.GET.get("page"))
    return render(request, "clientes/lista.html", {"pagina": pagina, "q": q, "orden": orden, **conteos_directorio()})


def conteos_directorio():
    """Contadores de las pestañas Clientes / Técnicos (una sola sección)."""
    from apps.trabajos.views import tecnicos_y_desactivados

    return {"n_clientes": Cliente.objects.filter(activo=True).count(),
            "n_tecnicos": tecnicos_y_desactivados().filter(is_active=True).count()}


@login_required
def detalle(request, pk):
    cliente = get_object_or_404(Cliente.objects.con_saldos(), pk=pk)
    facturas = Factura.objects.con_saldos().filter(cliente=cliente)
    abiertas = facturas.filter(anulada=False, saldo__gt=0)
    vencido = abiertas.filter(estado="VENCIDA").aggregate(s=Sum("saldo"))["s"] or 0
    return render(
        request,
        "clientes/detalle.html",
        {"cliente": cliente, "facturas": facturas, "abiertas": abiertas.count(), "vencido": vencido,
         "equipos": cliente.equipos.annotate(n_ordenes=Count("ordenes")).order_by("-activo", "nombre")},
    )


@login_required
def nuevo(request):
    form = ClienteForm(request.POST or None)
    if form.is_valid():
        cliente = form.save()
        messages.success(request, f"Cliente «{cliente}» creado.")
        siguiente = request.GET.get("next", "")
        if siguiente and url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            separador = "&" if "?" in siguiente else "?"
            return redirect(f"{siguiente}{separador}cliente={cliente.pk}")
        return redirect(cliente)
    return render(request, "clientes/form.html", {"form": form, "titulo": "Nuevo cliente"})


@login_required
def editar(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    form = ClienteForm(request.POST or None, instance=cliente)
    if form.is_valid():
        form.save()
        messages.success(request, "Cliente actualizado.")
        return redirect(cliente)
    return render(request, "clientes/form.html", {"form": form, "titulo": f"Editar {cliente}", "cliente": cliente})


@login_required
@require_POST
def rapido(request):
    """Alta rápida desde el formulario de factura (diálogo): responde JSON."""
    form = ClienteRapidoForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"errores": {k: [str(e) for e in v] for k, v in form.errors.items()}}, status=400)
    cliente = form.save()
    return JsonResponse({"id": cliente.pk, "nombre": cliente.nombre, "dias_credito": cliente.dias_credito})


# ---------------------------------------------------------------- equipos de los clientes


@requiere_rol(ADMINISTRADOR, MANAGER)
def equipos(request):
    q = request.GET.get("q", "").strip()
    tipo = request.GET.get("tipo", "")
    cliente_id = request.GET.get("cliente", "")
    ver = request.GET.get("ver", "activos")
    qs = Equipo.objects.select_related("cliente").annotate(
        n_ordenes=Count("ordenes", distinct=True),
        abiertas=Count("ordenes", filter=Q(ordenes__estado__in=["PENDIENTE", "EN_CURSO"]), distinct=True),
    ).order_by("-activo", "cliente__nombre", "nombre")
    if ver == "activos":
        qs = qs.filter(activo=True)
    elif ver == "retirados":
        qs = qs.filter(activo=False)
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(cliente__nombre__icontains=q) | Q(marca__icontains=q)
                       | Q(modelo__icontains=q) | Q(numero_serie__icontains=q) | Q(ubicacion__icontains=q))
    if tipo in Equipo.Tipo.values:
        qs = qs.filter(tipo=tipo)
    cliente = None
    if cliente_id.isdigit():
        cliente = Cliente.objects.filter(pk=cliente_id).first()
        if cliente:
            qs = qs.filter(cliente=cliente)
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "clientes/equipos.html", {
        "pagina": pagina, "q": q, "tipo": tipo, "tipos": Equipo.Tipo.choices, "cliente": cliente, "ver": ver,
        "clientes": Cliente.objects.filter(equipos__isnull=False).distinct().order_by("nombre"),
    })


def _guardar_equipo(request, equipo=None):
    inicial = None
    if not equipo and request.GET.get("cliente", "").isdigit():
        inicial = {"cliente": request.GET["cliente"]}
    form = EquipoForm(request.POST or None, instance=equipo, initial=inicial)
    if form.is_valid():
        e = form.save()
        messages.success(request, f"Equipo «{e.nombre}» guardado.")
        return redirect(e)
    return render(request, "clientes/equipo_form.html", {
        "form": form, "equipo": equipo, "titulo": f"Editar {equipo.nombre}" if equipo else "Nuevo equipo",
    })


@requiere_rol(ADMINISTRADOR, MANAGER)
def equipo_nuevo(request):
    return _guardar_equipo(request)


@requiere_rol(ADMINISTRADOR, MANAGER)
def equipo_editar(request, pk):
    return _guardar_equipo(request, get_object_or_404(Equipo, pk=pk))


@requiere_rol(ADMINISTRADOR, MANAGER)
def equipo(request, pk):
    e = get_object_or_404(Equipo.objects.select_related("cliente"), pk=pk)
    ordenes = e.ordenes.select_related("cliente").prefetch_related("tecnicos").order_by("-creado")
    return render(request, "clientes/equipo.html", {"e": e, "ordenes": ordenes})
