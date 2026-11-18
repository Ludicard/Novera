from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.facturas.models import Factura

from .forms import ClienteForm
from .models import Cliente


@login_required
def lista(request):
    q = request.GET.get("q", "").strip()
    clientes = Cliente.objects.con_saldos().annotate(num_facturas=Count("facturas"))
    if q:
        clientes = clientes.filter(Q(nombre__icontains=q) | Q(identificacion__icontains=q))
    if request.GET.get("con_saldo"):
        clientes = clientes.filter(saldo__gt=0)
    orden = request.GET.get("orden", "nombre")
    clientes = clientes.order_by("-saldo", "nombre") if orden == "saldo" else clientes.order_by("nombre")
    pagina = Paginator(clientes, 50).get_page(request.GET.get("page"))
    return render(request, "clientes/lista.html", {"pagina": pagina, "q": q, "orden": orden})


@login_required
def detalle(request, pk):
    cliente = get_object_or_404(Cliente.objects.con_saldos(), pk=pk)
    facturas = Factura.objects.con_saldos().filter(cliente=cliente)
    abiertas = facturas.filter(anulada=False, saldo__gt=0)
    vencido = abiertas.filter(estado="VENCIDA").aggregate(s=Sum("saldo"))["s"] or 0
    return render(
        request,
        "clientes/detalle.html",
        {"cliente": cliente, "facturas": facturas, "abiertas": abiertas.count(), "vencido": vencido},
    )


@login_required
def nuevo(request):
    form = ClienteForm(request.POST or None)
    if form.is_valid():
        cliente = form.save()
        messages.success(request, f"Cliente «{cliente}» creado.")
        return redirect(request.GET.get("next") or cliente.get_absolute_url())
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
