"""Datos del panel de inicio: indicadores, series para los gráficos y tablas.

Todo se calcula sobre las facturas **emitidas en el periodo filtrado** (y del cliente elegido),
salvo la serie «Cobrado» del gráfico mensual, que usa la fecha real de cada pago (flujo de caja).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django import forms
from django.db.models import Max, Min, Q

from apps.clientes.models import Cliente

from .models import Estado, Factura, Pago

CERO = Decimal("0.00")
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

PERIODOS = [
    ("mes", "Este mes"),
    ("3m", "Últimos 3 meses"),
    ("6m", "Últimos 6 meses"),
    ("12m", "Últimos 12 meses"),
    ("anio", "Este año"),
    ("anio_anterior", "Año anterior"),
    ("todo", "Todo el historial"),
    ("rango", "Rango personalizado"),
]
PERIODO_DEFECTO = "12m"

# Antigüedad de la cartera: (etiqueta, días vencidos desde, hasta)
TRAMOS = [
    ("Por vencer", None, 0),
    ("1–30 días", 1, 30),
    ("31–60 días", 31, 60),
    ("61–90 días", 61, 90),
    ("Más de 90", 91, None),
]

# Importaciones: el pago se registra con la fecha de emisión, no sirve para medir días de cobro
REFERENCIAS_IMPORTADAS = ("Importación", "Migración")


class FiltroPanelForm(forms.Form):
    periodo = forms.ChoiceField(choices=PERIODOS, required=False, label="Periodo")
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.none(),
        required=False,
        empty_label="Todos los clientes",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Se arma en cada petición: así solo salen los clientes de la empresa activa
        self.fields["cliente"].queryset = Cliente.objects.filter(facturas__isnull=False).distinct()


def sumar_meses(d, n):
    total = d.year * 12 + d.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)


def calcular_rango(periodo, desde, hasta, hoy):
    """Devuelve (desde, hasta) inclusivo según el preset elegido."""
    inicio_mes = hoy.replace(day=1)
    if periodo == "mes":
        return inicio_mes, hoy
    if periodo in {"3m", "6m", "12m"}:
        return sumar_meses(inicio_mes, -(int(periodo[:-1]) - 1)), hoy
    if periodo == "anio":
        return date(hoy.year, 1, 1), hoy
    if periodo == "anio_anterior":
        return date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)
    primera = Factura.objects.aggregate(m=Min("fecha_emision"))["m"] or inicio_mes
    if periodo == "todo":
        return primera, max(hoy, Factura.objects.aggregate(m=Max("fecha_emision"))["m"] or hoy)
    d, h = desde or primera, hasta or hoy
    return (d, h) if d <= h else (h, d)


def _etiqueta_mes(d, varios_anios):
    return f"{MESES_CORTOS[d.month - 1]} {d:%y}" if varios_anios else MESES_CORTOS[d.month - 1].capitalize()


def datos_panel(get, hoy):
    datos = get.copy() if get else {}
    if not datos.get("periodo"):
        datos["periodo"] = PERIODO_DEFECTO
    form = FiltroPanelForm(datos)
    form.is_valid()
    f = getattr(form, "cleaned_data", {})
    periodo = f.get("periodo") or PERIODO_DEFECTO
    desde, hasta = calcular_rango(periodo, f.get("desde"), f.get("hasta"), hoy)
    cliente = f.get("cliente")

    filtro_cliente = Q(cliente=cliente) if cliente else Q()
    facturas = list(
        Factura.objects.con_saldos(hoy)
        .filter(filtro_cliente, fecha_emision__gte=desde, fecha_emision__lte=hasta)
        .select_related("cliente")
    )
    vigentes = [x for x in facturas if not x.anulada]
    abiertas = [x for x in vigentes if x.saldo > 0]
    vencidas = [x for x in abiertas if x.estado == Estado.VENCIDA]

    def total(valores):
        return sum(valores, CERO).quantize(CERO)

    facturado = total(x.total for x in vigentes)
    cobrado = total(x.pagado for x in vigentes)
    por_cobrar = total(x.saldo for x in abiertas)
    vencido = total(x.saldo for x in vencidas)

    # Días promedio de cobro (emisión -> último pago) de las facturas pagadas con pagos reales
    pagadas = {x.pk: x for x in vigentes if x.estado == Estado.PAGADA}
    ultimos = (
        Pago.objects.filter(factura_id__in=pagadas)
        .exclude(Q(referencia__startswith=REFERENCIAS_IMPORTADAS[0]) | Q(referencia__startswith=REFERENCIAS_IMPORTADAS[1]))
        .values("factura_id")
        .annotate(ultimo=Max("fecha"))
    )
    dias = [max((u["ultimo"] - pagadas[u["factura_id"]].fecha_emision).days, 0) for u in ultimos]

    kpis = {
        "facturado": facturado,
        "num_facturas": len(vigentes),
        "cobrado": cobrado,
        "tasa_cobro": round(cobrado / facturado * 100) if facturado else None,
        "por_cobrar": por_cobrar,
        "num_abiertas": len(abiertas),
        "vencido": vencido,
        "num_vencidas": len(vencidas),
        "pct_vencido": round(vencido / por_cobrar * 100) if por_cobrar else None,
        "ticket": (facturado / len(vigentes)).quantize(Decimal("0.01")) if vigentes else CERO,
        "dias_cobro": round(sum(dias) / len(dias)) if dias else None,
        "num_anuladas": len(facturas) - len(vigentes),
        "clientes": len({x.cliente_id for x in vigentes}),
    }

    # --- Serie mensual: facturado (por emisión) vs cobrado (por fecha de pago)
    meses = []
    m = desde.replace(day=1)
    while m <= hasta:
        meses.append(m)
        m = sumar_meses(m, 1)
    meses = meses[-36:]  # como mucho 3 años de barras
    por_mes_fact = defaultdict(lambda: CERO)
    for x in vigentes:
        por_mes_fact[x.fecha_emision.replace(day=1)] += x.total
    por_mes_cobr = defaultdict(lambda: CERO)
    pagos = Pago.objects.filter(
        Q(factura__cliente=cliente) if cliente else Q(), factura__anulada=False, fecha__gte=desde, fecha__lte=hasta
    ).values_list("fecha", "monto")
    for fecha, monto in pagos:
        por_mes_cobr[fecha.replace(day=1)] += monto
    varios_anios = len({mm.year for mm in meses}) > 1
    mensual = [
        {
            "mes": _etiqueta_mes(mm, varios_anios),
            "mes_largo": f"{MESES_CORTOS[mm.month - 1]} {mm.year}",
            "facturado": float(por_mes_fact[mm]),
            "cobrado": float(por_mes_cobr[mm]),
        }
        for mm in meses
    ]

    # --- Antigüedad de lo pendiente
    tramos = [{"tramo": t[0], "monto": CERO, "n": 0} for t in TRAMOS]
    for x in abiertas:
        atraso = (hoy - x.fecha_cobro).days if x.fecha_cobro else 0
        for i, (_, ini, fin) in enumerate(TRAMOS):
            if (ini is None or atraso >= ini) and (fin is None or atraso <= fin):
                tramos[i]["monto"] += x.saldo
                tramos[i]["n"] += 1
                break

    # --- Facturas por estado
    orden_estados = [Estado.PAGADA, Estado.PARCIAL, Estado.PENDIENTE, Estado.VENCIDA]
    estados = {e: {"estado": e.label, "clave": e.value, "monto": CERO, "n": 0} for e in orden_estados}
    for x in vigentes:
        if x.estado in estados:
            estados[x.estado]["monto"] += x.total
            estados[x.estado]["n"] += 1

    # --- Clientes: facturación y saldo
    por_cliente = defaultdict(lambda: {"facturado": CERO, "saldo": CERO, "vencido": CERO, "n": 0, "abiertas": 0})
    nombres = {}
    for x in vigentes:
        c = por_cliente[x.cliente_id]
        nombres[x.cliente_id] = x.cliente.nombre if x.cliente else "(sin cliente)"
        c["facturado"] += x.total
        c["n"] += 1
        if x.saldo > 0:
            c["saldo"] += x.saldo
            c["abiertas"] += 1
            if x.estado == Estado.VENCIDA:
                c["vencido"] += x.saldo
    filas_clientes = [{"id": k, "nombre": nombres[k], **v} for k, v in por_cliente.items()]
    top_clientes = sorted(filas_clientes, key=lambda c: -c["facturado"])[:8]
    saldos_clientes = sorted((c for c in filas_clientes if c["saldo"] > 0), key=lambda c: -c["saldo"])[:10]

    proximas = (
        Factura.objects.por_cobrar(hoy)
        .filter(filtro_cliente, fecha_cobro__gte=hoy, fecha_cobro__lte=hoy + timedelta(days=7))
        .select_related("cliente")
        .order_by("fecha_cobro")[:8]
    )

    graficos = {
        "mensual": mensual,
        "tramos": [{"tramo": t["tramo"], "monto": float(t["monto"]), "n": t["n"]} for t in tramos],
        "estados": [{**e, "monto": float(e["monto"])} for e in estados.values()],
        "clientes": [
            {"id": c["id"], "nombre": c["nombre"], "facturado": float(c["facturado"]), "saldo": float(c["saldo"]), "n": c["n"]}
            for c in top_clientes
        ],
    }
    filtro_lista = {"emitida_desde": desde.isoformat(), "emitida_hasta": hasta.isoformat()}
    if cliente:
        filtro_lista["cliente"] = cliente.pk
    return {
        "form": form,
        "filtro_lista": urlencode(filtro_lista),
        "periodo": periodo,
        "desde": desde,
        "hasta": hasta,
        "cliente": cliente,
        "kpis": kpis,
        "graficos": graficos,
        "mensual": mensual,
        "tramos": tramos,
        "vencidas": sorted(vencidas, key=lambda x: x.fecha_cobro)[:8],
        "proximas": proximas,
        "saldos_clientes": saldos_clientes,
    }
