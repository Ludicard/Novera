"""Importación del Excel histórico a Novera.

Lee la hoja "Facturas" (columnas: Numero de Factura, Periodo, Fecha, Tipo, Cliente, Objeto,
Fecha Cobro, Valor, IVA, TOTAL, Estado) y el catálogo de clientes de la hoja "Altas".

El Excel tiene datos muy heterogéneos, así que cada fila se normaliza y se anotan avisos:
- Números de factura con espacios, recibos escritos de varias formas ("Reibo 066", "Recibo357").
- Periodo como "Enero", "julio - 2025" o una fecha.
- Fecha de cobro a veces como texto libre ("lunes 23 de nov").
- IVA vacío con el 12% incluido en el total (2024) o explícito al 15% (2025+).
- Estado escrito a mano o "#REF!" (la hoja Pagos fue borrada).
- El mismo cliente escrito de varias formas ("Edificio Central", "edf central").

Flujo: `analizar()` no toca la base de datos (vista previa); `aplicar()` guarda todo en una transacción.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction

from apps.clientes.models import Cliente

from .models import Factura, Pago, redondear

MESES = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "sept": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}
TASAS_IVA = [Decimal("0"), Decimal("5"), Decimal("12"), Decimal("15")]
PATRON_SRI = re.compile(r"^\d{3}-\d{3}-\d{9}$")
PATRON_RECIBO = re.compile(r"^re[ci]{0,2}bo\s*0*(\d+)$", re.IGNORECASE)
PREFIJOS_CLIENTE = {"edificio", "edf", "edif", "ed"}

COLUMNAS = {
    "numero de factura": "numero",
    "periodo": "periodo",
    "fecha": "fecha",
    "tipo": "tipo",
    "cliente": "cliente",
    "objeto": "objeto",
    "fecha cobro": "fecha_cobro",
    "valor": "valor",
    "iva": "iva",
    "total": "total",
    "estado": "estado",
}

ESTADO_DESCONOCIDO_OPCIONES = [
    ("pendiente", "Pendientes de cobro (recomendado: luego registras los pagos reales)"),
    ("pagada", "Pagadas (se crea un pago por el total)"),
]


# ---------------------------------------------------------------- normalizadores


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor)).strip()


def a_decimal(valor):
    """Número del Excel a Decimal. Acepta '6508,91', '1.234,56', '$ 80'. None si no es número."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        return redondear(Decimal(str(valor)))
    s = str(valor).strip().replace("$", "").replace(" ", "")
    if not s or s.startswith("#"):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return redondear(Decimal(s))
    except InvalidOperation:
        return None


def a_fecha(valor):
    """Fecha del Excel. Acepta datetime, 'dd/mm/aaaa', 'm/d/aaaa' (si el día no cuadra) y 'aaaa-mm-dd'."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    for formato in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, formato).date()
        except ValueError:
            continue
    return None


def a_periodo(valor, fecha_ref):
    """Periodo ('Enero', 'julio - 2025', fecha) al primer día del mes."""
    if valor is None or texto(valor) == "":
        return fecha_ref.replace(day=1) if fecha_ref else None
    f = a_fecha(valor)
    if f:
        return f.replace(day=1)
    s = _sin_tildes(texto(valor).lower())
    mes = next((n for nombre, n in MESES.items() if re.search(rf"\b{nombre}\b", s)), None)
    if not mes:
        return fecha_ref.replace(day=1) if fecha_ref else None
    anio = re.search(r"(20\d{2})", s)
    if anio:
        return date(int(anio.group(1)), mes, 1)
    if not fecha_ref:
        return None
    anio = fecha_ref.year
    if mes - fecha_ref.month > 6:  # p. ej. "Diciembre" facturado en enero
        anio -= 1
    elif fecha_ref.month - mes > 6:  # p. ej. "Enero" facturado en diciembre (anticipado)
        anio += 1
    return date(anio, mes, 1)


def normalizar_numero(valor):
    """Devuelve (numero, tipo, es_estandar)."""
    s = texto(valor)
    m = PATRON_RECIBO.match(s)
    if m:
        return f"Recibo {int(m.group(1)):03d}", Factura.Tipo.RECIBO, True
    if PATRON_SRI.match(s):
        return s, Factura.Tipo.FACTURA, True
    return s, Factura.Tipo.FACTURA, s.isdigit()


def normalizar_identificacion(valor):
    """RUC/cédula: el Excel los guarda como número y pierde el cero inicial."""
    s = re.sub(r"\D", "", texto(valor))
    if len(s) in (9, 12):
        s = "0" + s
    return s if len(s) in (10, 13) else ""


def clave_cliente(nombre):
    """Clave para reconocer el mismo cliente escrito de formas distintas."""
    s = _sin_tildes(texto(nombre).lower())
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    palabras = s.split()
    while palabras and palabras[0] in PREFIJOS_CLIENTE:
        palabras = palabras[1:]
    return " ".join(palabras)


def nombre_presentable(nombre):
    n = texto(nombre)
    return n.title() if n.islower() else n


def inferir_montos(subtotal, iva, total):
    """Devuelve (subtotal, porcentaje, iva, total, avisos) o None si no hay montos."""
    avisos = []
    if subtotal is None and total is None:
        return None
    if subtotal is None:
        subtotal = total - (iva or Decimal("0"))
        avisos.append("Sin valor: se calculó como total − IVA")

    if iva is not None:
        porcentaje = _tasa_cercana(iva, subtotal)
        esperado = subtotal + iva
        if total is None:
            total = esperado
        elif abs(total - esperado) > Decimal("0.02"):
            avisos.append(f"El total ({total}) no coincide con valor + IVA ({esperado}); se conserva el total")
        return subtotal, porcentaje, iva, total, avisos

    if total is None:
        return subtotal, Decimal("0"), Decimal("0.00"), subtotal, avisos
    iva = redondear(total - subtotal)
    porcentaje = _tasa_cercana(iva, subtotal)
    if iva < 0:
        avisos.append(f"El total ({total}) es menor que el valor ({subtotal})")
    elif iva > 0 and porcentaje not in TASAS_IVA:
        avisos.append(f"IVA implícito de {porcentaje}% no estándar")
    return subtotal, porcentaje, iva, total, avisos


def _tasa_cercana(iva, subtotal):
    if not subtotal:
        return Decimal("0")
    pct = iva / subtotal * 100
    cercana = min(TASAS_IVA, key=lambda t: abs(t - pct))
    return cercana if abs(cercana - pct) <= Decimal("0.6") else redondear(pct)


# ---------------------------------------------------------------- análisis


@dataclass
class FilaImportada:
    fila: int
    numero: str = ""
    tipo: str = Factura.Tipo.FACTURA
    cliente: str = ""
    clave: str = ""
    periodo: date | None = None
    fecha_emision: date | None = None
    fecha_cobro: date | None = None
    objeto: str = ""
    subtotal: Decimal = Decimal("0.00")
    porcentaje_iva: Decimal = Decimal("0")
    iva: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    estado_origen: str = ""
    accion: str = "pendiente"  # pendiente | pagada | anulada
    notas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    omitida: bool = False


@dataclass
class Resultado:
    filas: list[FilaImportada]
    catalogo: dict  # clave -> (nombre, identificacion)
    errores: list[str] = field(default_factory=list)

    @property
    def importables(self):
        return [f for f in self.filas if not f.omitida]

    @property
    def omitidas(self):
        return [f for f in self.filas if f.omitida]

    @property
    def con_avisos(self):
        return [f for f in self.importables if f.avisos]

    def resumen(self):
        filas = self.importables
        existentes = {clave_cliente(n) for n in Cliente.objects.values_list("nombre", flat=True)}
        claves_nuevas = ({f.clave for f in filas if f.clave} | set(self.catalogo)) - existentes
        return {
            "filas": len(filas),
            "omitidas": len(self.omitidas),
            "con_avisos": len(self.con_avisos),
            "pagadas": sum(1 for f in filas if f.accion == "pagada"),
            "pendientes": sum(1 for f in filas if f.accion == "pendiente"),
            "anuladas": sum(1 for f in filas if f.accion == "anulada"),
            "por_cobrar": sum((f.total for f in filas if f.accion == "pendiente"), Decimal("0")),
            "clientes_nuevos": len(claves_nuevas),
        }


def _buscar_hoja(wb, nombre):
    for ws in wb.worksheets:
        if ws.title.strip().lower() == nombre:
            return ws
    return None


def _leer_catalogo(wb):
    ws = _buscar_hoja(wb, "altas")
    catalogo = {}
    if ws is None:
        return catalogo
    encabezado = [_sin_tildes(texto(c.value).lower()) for c in ws[1]]
    try:
        col_nombre = encabezado.index("cliente")
        col_ruc = encabezado.index("ruc")
    except ValueError:
        return catalogo
    for fila in ws.iter_rows(min_row=2, values_only=True):
        nombre = texto(fila[col_nombre]) if col_nombre < len(fila) else ""
        if not nombre:
            continue
        clave = clave_cliente(nombre)
        ruc = normalizar_identificacion(fila[col_ruc]) if col_ruc < len(fila) else ""
        if clave not in catalogo or (ruc and not catalogo[clave][1]):
            catalogo[clave] = (nombre_presentable(nombre), ruc)
    return catalogo


def analizar(origen, estado_desconocido="pendiente"):
    """Lee el Excel y devuelve un Resultado sin escribir nada en la base de datos."""
    wb = openpyxl.load_workbook(origen, data_only=True)
    ws = _buscar_hoja(wb, "facturas")
    if ws is None:
        return Resultado(filas=[], catalogo={}, errores=["El archivo no tiene una hoja llamada «Facturas»."])

    encabezado = [_sin_tildes(texto(c.value).lower()) for c in ws[1]]
    cols = {COLUMNAS[h]: i for i, h in enumerate(encabezado) if h in COLUMNAS}
    faltan = {"numero", "cliente", "valor", "total"} - set(cols)
    if faltan:
        return Resultado(
            filas=[], catalogo={}, errores=[f"Faltan columnas en la hoja Facturas: {', '.join(sorted(faltan))}"]
        )

    # Si existe la tabla de Excel, solo se leen sus filas (ignora apuntes sueltos al lado/debajo).
    ultima = ws.max_row
    for tabla in ws.tables.values():
        ref = tabla.ref if hasattr(tabla, "ref") else tabla
        ultima = openpyxl.utils.cell.range_boundaries(ref)[3]
        break

    catalogo = _leer_catalogo(wb)
    existentes = set(Factura.objects.values_list("numero", flat=True))
    vistos = {}
    filas = []
    fecha_anterior = None

    for n, valores in enumerate(ws.iter_rows(min_row=2, max_row=ultima, values_only=True), start=2):
        def v(campo):
            i = cols.get(campo)
            return valores[i] if i is not None and i < len(valores) else None

        if all(x is None or texto(x) == "" for x in valores[: max(cols.values()) + 1]):
            continue
        fila = FilaImportada(fila=n)
        filas.append(fila)

        numero, tipo, estandar = normalizar_numero(v("numero"))
        if not numero:
            fila.omitida = True
            fila.avisos.append("Fila sin número de factura")
            continue
        fila.numero, fila.tipo = numero, tipo
        if not estandar:
            fila.avisos.append("Número con formato no estándar")

        estado = _sin_tildes(texto(v("estado")).lower())
        fila.estado_origen = texto(v("estado"))
        montos = inferir_montos(a_decimal(v("valor")), a_decimal(v("iva")), a_decimal(v("total")))
        if montos is None and estado != "anulada":
            fila.omitida = True
            fila.avisos.append("Sin valor ni total (número reservado sin datos)")
            continue
        fila.cliente = nombre_presentable(v("cliente"))
        fila.clave = clave_cliente(fila.cliente)
        if fila.clave in catalogo:
            fila.cliente = catalogo[fila.clave][0]
        fila.objeto = texto(v("objeto"))[:255]

        # Fechas
        fila.fecha_emision = a_fecha(v("fecha"))
        if not fila.fecha_emision:
            if fecha_anterior:
                fila.fecha_emision = fecha_anterior
                fila.avisos.append("Sin fecha de emisión: se tomó la de la fila anterior")
            else:
                fila.omitida = True
                fila.avisos.append("Sin fecha de emisión")
                continue
        fecha_anterior = fila.fecha_emision
        fila.periodo = a_periodo(v("periodo"), fila.fecha_emision)
        cobro_original = v("fecha_cobro")
        fila.fecha_cobro = a_fecha(cobro_original)
        if cobro_original is not None and not fila.fecha_cobro and texto(cobro_original):
            fila.notas.append(f"Fecha de cobro en el Excel: «{texto(cobro_original)}»")
            fila.avisos.append(f"Fecha de cobro no reconocida («{texto(cobro_original)}»)")

        # Montos
        if estado == "anulada":
            fila.accion = "anulada"
            if montos:
                fila.subtotal, fila.porcentaje_iva, fila.iva, fila.total, _ = montos
        else:
            fila.subtotal, fila.porcentaje_iva, fila.iva, fila.total, avisos = montos
            fila.avisos.extend(avisos)
            if estado == "pagada":
                fila.accion = "pagada"
            elif estado == "no pagada":
                fila.accion = "pendiente"
            else:
                fila.accion = estado_desconocido
                fila.avisos.append(f"Estado desconocido en el Excel («{fila.estado_origen or 'vacío'}»)")
            if not fila.cliente:
                fila.avisos.append("Sin cliente")

        # Duplicados
        if fila.numero in existentes:
            fila.omitida = True
            fila.avisos.append("Ya existe en Novera")
            continue
        if fila.numero in vistos:
            vistos[fila.numero] += 1
            original = fila.numero
            fila.numero = f"{original} (dup {vistos[original]})"
            fila.notas.append(f"Número repetido en el Excel: {original}")
            fila.avisos.append("Número repetido en el Excel: se importa con sufijo para revisarlo")
        else:
            vistos[fila.numero] = 1

    return Resultado(filas=filas, catalogo=catalogo)


# ---------------------------------------------------------------- aplicar


@transaction.atomic
def aplicar(resultado, usuario=None, dias_credito=30):
    """Crea clientes, facturas y pagos. Devuelve un dict con lo creado."""
    clientes = {clave_cliente(c.nombre): c for c in Cliente.objects.all()}
    creados = {"clientes": 0, "facturas": 0, "pagos": 0}

    def obtener_cliente(clave, nombre, identificacion=""):
        if not clave:
            return None
        cliente = clientes.get(clave)
        if cliente is None:
            cliente = Cliente.objects.create(
                nombre=nombre[:200], identificacion=identificacion, dias_credito=dias_credito
            )
            clientes[clave] = cliente
            creados["clientes"] += 1
        elif identificacion and not cliente.identificacion:
            cliente.identificacion = identificacion
            cliente.save(update_fields=["identificacion"])
        return cliente

    for clave, (nombre, ruc) in resultado.catalogo.items():
        obtener_cliente(clave, nombre, ruc)

    for fila in resultado.importables:
        factura = Factura.objects.create(
            numero=fila.numero[:40],
            tipo=fila.tipo,
            cliente=obtener_cliente(fila.clave, fila.cliente),
            periodo=fila.periodo,
            fecha_emision=fila.fecha_emision,
            dias_credito=dias_credito,
            fecha_cobro=fila.fecha_cobro,
            objeto=fila.objeto,
            subtotal=fila.subtotal,
            porcentaje_iva=fila.porcentaje_iva,
            iva=fila.iva,
            total=fila.total,
            anulada=fila.accion == "anulada",
            fecha_anulacion=fila.fecha_emision if fila.accion == "anulada" else None,
            motivo_anulacion="Anulada en el Excel" if fila.accion == "anulada" else "",
            notas="\n".join(fila.notas + [f"Importada de la fila {fila.fila} del Excel."]),
            importada=True,
            creado_por=usuario,
        )
        creados["facturas"] += 1
        if fila.accion == "pagada" and factura.total > 0:
            Pago.objects.create(
                factura=factura,
                fecha=fila.fecha_cobro or fila.fecha_emision,
                forma=Pago.Forma.OTRO,
                referencia="Migración Excel",
                monto=factura.total,
                notas=f"Marcada como «{fila.estado_origen or 'pagada'}» en el Excel",
                creado_por=usuario,
            )
            creados["pagos"] += 1
    return creados
