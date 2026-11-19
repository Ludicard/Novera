"""Importación de facturas desde Excel a Novera.

Formatos reconocidos (se detectan solos):

1. **Reporte de Factura de FactureroMovil** (formato principal): título en las primeras filas y
   encabezados «Fecha de emision · No Factura · Clave de acceso · Base imponible IVA · … · Valor total ·
   NID Cliente · Cliente · Estado · … · Cobrada · Info. adicional · Plazo …». De «Info. adicional» se
   extraen dirección, email y teléfono del cliente y el «Mes del Servicio» (periodo).

2. **Excel histórico** («Base Celeste»): lee la hoja "Facturas" (columnas: Numero de Factura, Periodo, Fecha, Tipo, Cliente, Objeto,
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

from .models import Factura, Pago, clave_numero, redondear

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
# «MEGA SANTAMARIA S.A.» y «Mega Santamaria» son el mismo cliente
SUFIJOS_CLIENTE = {"s", "a", "sa", "cia", "ltda", "c", "ca", "cltda", "sas"}
PATRON_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Reporte de Factura de FactureroMovil: encabezado normalizado -> campo
COLUMNAS_FM = {
    "fecha de emision": "fecha",
    "no factura": "numero",
    "clave de acceso": "clave_acceso",
    "base imponible iva": "base_iva",
    "base imponible 0%": "base_0",
    "base imponible 5%": "base_5",
    "base imponible 8%": "base_8",
    "base imponible no iva": "base_no_iva",
    "iva": "iva",
    "iva 5%": "iva_5",
    "iva 8%": "iva_8",
    "ice": "ice",
    "total descuento": "descuento",
    "valor total": "total",
    "nid cliente": "nid",
    "cliente": "cliente",
    "estado": "estado",
    "por cobrar": "por_cobrar",
    "saldo cobrar": "saldo_cobrar",
    "cobrada": "cobrada",
    "info. adicional": "info",
    "info. adic": "info",
    "plazo": "plazo",
}
SI = {"si", "s", "yes", "cobrada", "pagada"}

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
    while len(palabras) > 1 and palabras[-1] in SUFIJOS_CLIENTE:
        palabras = palabras[:-1]
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


# ---------------------------------------------------------------- duplicados


class Registro:
    """Números (canónicos) y claves de acceso ya vistos: en Novera o antes en el mismo archivo."""

    def __init__(self, desde_bd=True):
        self.numeros = set()
        self.claves = set()
        if desde_bd:
            for numero, clave in Factura.objects.values_list("numero", "clave_acceso"):
                self.agregar(numero, clave)

    def contiene(self, numero, clave_acceso=""):
        return clave_numero(numero) in self.numeros or bool(clave_acceso and clave_acceso in self.claves)

    def agregar(self, numero, clave_acceso=""):
        self.numeros.add(clave_numero(numero))
        if clave_acceso:
            self.claves.add(clave_acceso)


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
    abonado: Decimal = Decimal("0.00")  # cobro parcial informado por FactureroMovil
    dias_credito: int | None = None
    clave_acceso: str = ""
    identificacion: str = ""
    email: str = ""
    telefono: str = ""
    direccion: str = ""
    origen: str = "Excel"
    notas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    omitida: bool = False
    ya_existe: bool = False


@dataclass
class Resultado:
    filas: list[FilaImportada]
    catalogo: dict  # clave -> (nombre, identificacion)
    errores: list[str] = field(default_factory=list)
    formato: str = "Excel histórico"

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
        claves = set()
        rucs = set()
        for nombre, ruc in Cliente.objects.values_list("nombre", "identificacion"):
            claves.add(clave_cliente(nombre))
            rucs.add(ruc)
        nuevos = set()
        for f in filas:
            if (f.identificacion and f.identificacion in rucs) or (f.clave and f.clave in claves):
                continue
            if f.clave or f.identificacion:
                nuevos.add(f.identificacion or f.clave)
                rucs.add(f.identificacion)
                claves.add(f.clave)
        claves_nuevas = nuevos | (set(self.catalogo) - claves)
        return {
            "filas": len(filas),
            "omitidas": len(self.omitidas),
            "ya_existen": sum(1 for f in self.filas if f.ya_existe),
            "con_avisos": len(self.con_avisos),
            "pagadas": sum(1 for f in filas if f.accion == "pagada"),
            "pendientes": sum(1 for f in filas if f.accion == "pendiente"),
            "anuladas": sum(1 for f in filas if f.accion == "anulada"),
            "por_cobrar": sum((f.total - f.abonado for f in filas if f.accion == "pendiente"), Decimal("0")),
            "facturado": sum((f.total for f in filas if f.accion != "anulada"), Decimal("0")),
            "clientes_nuevos": len(claves_nuevas),
            "formato": self.formato,
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
    """Lee el Excel (detecta el formato) y devuelve un Resultado sin escribir en la base de datos."""
    wb = openpyxl.load_workbook(origen, data_only=True)
    facturero = _detectar_facturero(wb)
    if facturero:
        return _analizar_facturero(*facturero, estado_desconocido=estado_desconocido)
    ws = _buscar_hoja(wb, "facturas")
    if ws is None:
        return Resultado(
            filas=[],
            catalogo={},
            errores=[
                "No se reconoce el formato. Sube el «Reporte de Factura» descargado de FactureroMovil "
                "(o el Excel histórico con la hoja «Facturas»)."
            ],
        )
    return _analizar_historico(wb, ws, estado_desconocido)


# ---------------------------------------------------------------- FactureroMovil


def _encabezado(valores):
    return [_sin_tildes(texto(c).lower()) for c in valores]


def _detectar_facturero(wb):
    """Busca la fila de encabezados del Reporte de Factura en las primeras filas de cada hoja."""
    for ws in wb.worksheets:
        for n, valores in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
            encabezado = _encabezado(valores)
            if "no factura" in encabezado and "valor total" in encabezado:
                cols = {}
                for i, h in enumerate(encabezado):
                    if h in COLUMNAS_FM and COLUMNAS_FM[h] not in cols:
                        cols[COLUMNAS_FM[h]] = i
                return ws, n, cols
    return None


def _nombra_un_mes(valor):
    s = _sin_tildes(texto(valor).lower())
    return any(re.search(rf"\b{nombre}\b", s) for nombre in MESES)


def _leer_info_adicional(info):
    """«Dirección: X | Email: a@b | Mes del Servicio: Enero | …» -> dict de datos y lista de extras."""
    datos = {"direccion": "", "email": "", "telefono": "", "mes": ""}
    extras = []
    for parte in texto(info).split("|"):
        if ":" not in parte:
            if parte.strip():
                extras.append(parte.strip())
            continue
        clave, valor = (x.strip() for x in parte.split(":", 1))
        compacta = re.sub(r"[^a-z]", "", _sin_tildes(clave.lower()))
        if not valor:
            continue
        if compacta == "direccion":
            datos["direccion"] = valor[:255]
        elif compacta in {"email", "correo", "observaciones"} and PATRON_EMAIL.search(valor):
            if not datos["email"]:
                datos["email"] = PATRON_EMAIL.search(valor).group(0)[:254]
        elif compacta.startswith("telefono"):
            datos["telefono"] = valor[:30]
        elif compacta.startswith("proveedor"):
            continue
        else:
            # «Mes del Servicio», con sus erratas («Mes ddel Servicio», «Me s del Servicio», …)
            if compacta.startswith("mes") and not datos["mes"] and _nombra_un_mes(valor):
                datos["mes"] = valor
            extras.append(f"{clave}: {valor}")
    return datos, extras


def _analizar_facturero(ws, fila_encabezado, cols, estado_desconocido="pendiente"):
    faltan = {"numero", "fecha", "cliente", "total"} - set(cols)
    if faltan:
        return Resultado(
            filas=[], catalogo={}, formato="FactureroMovil",
            errores=[f"Al reporte de FactureroMovil le faltan columnas: {', '.join(sorted(faltan))}"],
        )

    existentes = Registro()
    vistos = Registro(desde_bd=False)
    filas = []
    for n, valores in enumerate(ws.iter_rows(min_row=fila_encabezado + 1, values_only=True), start=fila_encabezado + 1):
        def v(campo):
            i = cols.get(campo)
            return valores[i] if i is not None and i < len(valores) else None

        if all(x is None or texto(x) == "" for x in valores):
            continue
        fila = FilaImportada(fila=n, origen="FactureroMovil")
        numero, tipo, estandar = normalizar_numero(v("numero"))
        if not numero:
            continue  # filas de totales o notas al pie
        filas.append(fila)
        fila.numero, fila.tipo = numero, tipo
        if not estandar:
            fila.avisos.append("Número con formato no estándar")
        fila.clave_acceso = re.sub(r"\D", "", texto(v("clave_acceso")))[:49]

        fila.fecha_emision = a_fecha(v("fecha"))
        if not fila.fecha_emision:
            fila.omitida = True
            fila.avisos.append("Sin fecha de emisión")
            continue

        # Estado en el SRI
        fila.estado_origen = texto(v("estado"))
        estado = _sin_tildes(fila.estado_origen.lower())
        if "anulad" in estado:
            fila.accion = "anulada"
        elif estado and ("no autoriz" in estado or "autoriz" not in estado):
            fila.omitida = True
            fila.avisos.append(f"Estado «{fila.estado_origen}»: no está autorizada por el SRI")
            continue

        # Cliente y datos de contacto
        fila.cliente = nombre_presentable(v("cliente"))
        fila.clave = clave_cliente(fila.cliente)
        fila.identificacion = normalizar_identificacion(v("nid"))
        if not fila.cliente:
            fila.avisos.append("Sin cliente")
        info, extras = _leer_info_adicional(v("info"))
        fila.direccion, fila.email, fila.telefono = info["direccion"], info["email"], info["telefono"]
        fila.objeto = " | ".join(extras)[:255]
        fila.periodo = a_periodo(info["mes"] or None, fila.fecha_emision)

        plazo = a_decimal(v("plazo"))
        if plazo and plazo > 0:
            fila.dias_credito = int(plazo)

        # Montos
        def suma(*campos):
            return redondear(sum((a_decimal(v(c)) or Decimal("0")) for c in campos))

        fila.subtotal = suma("base_iva", "base_0", "base_5", "base_8", "base_no_iva")
        fila.iva = suma("iva", "iva_5", "iva_8")
        total = a_decimal(v("total"))
        fila.total = total if total is not None else redondear(fila.subtotal + fila.iva + suma("ice"))
        base_iva, base_5, base_8 = (a_decimal(v(c)) or Decimal("0") for c in ("base_iva", "base_5", "base_8"))
        if base_iva:
            fila.porcentaje_iva = _tasa_cercana(a_decimal(v("iva")) or Decimal("0"), base_iva)
        elif base_5:
            fila.porcentaje_iva = Decimal("5")
        elif base_8:
            fila.porcentaje_iva = Decimal("8")
        else:
            fila.porcentaje_iva = Decimal("0")
        if sum(1 for b in (base_iva, base_5, base_8, suma("base_0", "base_no_iva")) if b) > 1:
            fila.avisos.append("Combina varias tarifas de IVA")
        esperado = redondear(fila.subtotal + fila.iva + suma("ice"))
        if abs(fila.total - esperado) > Decimal("0.02"):
            fila.avisos.append(f"El valor total ({fila.total}) no coincide con bases + IVA ({esperado})")
        if fila.total <= 0 and fila.accion != "anulada":
            fila.omitida = True
            fila.avisos.append("Valor total en cero")
            continue

        # Cobro: FactureroMovil solo lo informa si se usa su módulo de cuentas por cobrar
        if fila.accion != "anulada":
            cobrada = _sin_tildes(texto(v("cobrada")).lower())
            por_cobrar = _sin_tildes(texto(v("por_cobrar")).lower())
            saldo = a_decimal(v("saldo_cobrar"))
            if cobrada in SI:
                fila.accion = "pagada"
            elif por_cobrar in SI:
                fila.accion = "pendiente"
                if saldo is not None and Decimal("0") < saldo < fila.total:
                    fila.abonado = redondear(fila.total - saldo)
            else:
                fila.accion = estado_desconocido

        if existentes.contiene(fila.numero, fila.clave_acceso):
            fila.omitida = True
            fila.ya_existe = True
            fila.avisos.append("Ya existe en Novera")
        elif vistos.contiene(fila.numero, fila.clave_acceso):
            fila.omitida = True
            fila.avisos.append("Repetida en el archivo")
        vistos.agregar(fila.numero, fila.clave_acceso)

    if not filas:
        return Resultado(filas=[], catalogo={}, formato="FactureroMovil", errores=["El reporte no tiene facturas."])
    return Resultado(filas=filas, catalogo={}, formato="FactureroMovil")


# ---------------------------------------------------------------- Excel histórico


def _analizar_historico(wb, ws, estado_desconocido):
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
    existentes = Registro()
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

        # Duplicados (una repetición dentro del Excel se importa con sufijo para revisarla)
        clave = clave_numero(fila.numero)
        if existentes.contiene(fila.numero) and clave not in vistos:
            fila.omitida = True
            fila.ya_existe = True
            fila.avisos.append("Ya existe en Novera")
            vistos[clave] = 1
            continue
        if clave in vistos:
            vistos[clave] += 1
            original = fila.numero
            fila.numero = f"{original} (dup {vistos[clave]})"
            if existentes.contiene(fila.numero):
                fila.omitida = True
                fila.ya_existe = True
                fila.avisos.append("Ya existe en Novera")
                continue
            fila.notas.append(f"Número repetido en el Excel: {original}")
            fila.avisos.append("Número repetido en el Excel: se importa con sufijo para revisarlo")
        else:
            vistos[clave] = 1

    return Resultado(filas=filas, catalogo=catalogo)


# ---------------------------------------------------------------- aplicar


@transaction.atomic
def aplicar(resultado, usuario=None, dias_credito=30):
    """Crea clientes, facturas y pagos. Devuelve un dict con lo creado."""
    todos = list(Cliente.objects.all())
    por_clave = {clave_cliente(c.nombre): c for c in todos}
    por_ruc = {c.identificacion: c for c in todos if c.identificacion}
    creados = {"clientes": 0, "facturas": 0, "pagos": 0, "saltadas": 0}
    # Se vuelve a comprobar aquí: entre la vista previa y la confirmación pudo importarse lo mismo
    registradas = Registro()

    def obtener_cliente(clave, nombre, identificacion="", email="", telefono="", direccion=""):
        if not clave and not identificacion:
            return None
        cliente = por_ruc.get(identificacion) if identificacion else None
        cliente = cliente or por_clave.get(clave)
        if cliente is None:
            cliente = Cliente.objects.create(
                nombre=nombre[:200], identificacion=identificacion, email=email, telefono=telefono,
                direccion=direccion, dias_credito=dias_credito,
            )
            creados["clientes"] += 1
        else:
            cambios = []
            for campo, valor in (
                ("identificacion", identificacion), ("email", email), ("telefono", telefono), ("direccion", direccion)
            ):
                if valor and not getattr(cliente, campo):
                    setattr(cliente, campo, valor)
                    cambios.append(campo)
            if cambios:
                cliente.save(update_fields=cambios)
        por_clave.setdefault(clave, cliente)
        if cliente.identificacion:
            por_ruc.setdefault(cliente.identificacion, cliente)
        return cliente

    for clave, (nombre, ruc) in resultado.catalogo.items():
        obtener_cliente(clave, nombre, ruc)

    for fila in resultado.importables:
        if registradas.contiene(fila.numero, fila.clave_acceso):
            creados["saltadas"] += 1
            continue
        registradas.agregar(fila.numero, fila.clave_acceso)
        cliente = obtener_cliente(
            fila.clave, fila.cliente, fila.identificacion, fila.email, fila.telefono, fila.direccion
        )
        dias = fila.dias_credito if fila.dias_credito is not None else (cliente.dias_credito if cliente else dias_credito)
        anulada = fila.accion == "anulada"
        factura = Factura.objects.create(
            numero=fila.numero[:40],
            tipo=fila.tipo,
            cliente=cliente,
            periodo=fila.periodo,
            fecha_emision=fila.fecha_emision,
            dias_credito=dias,
            fecha_cobro=fila.fecha_cobro,
            objeto=fila.objeto,
            subtotal=fila.subtotal,
            porcentaje_iva=fila.porcentaje_iva,
            iva=fila.iva,
            total=fila.total,
            clave_acceso=fila.clave_acceso,
            anulada=anulada,
            fecha_anulacion=fila.fecha_emision if anulada else None,
            motivo_anulacion=f"Anulada en {fila.origen}" if anulada else "",
            notas="\n".join(fila.notas + [f"Importada de la fila {fila.fila} ({fila.origen})."]),
            importada=True,
            creado_por=usuario,
        )
        creados["facturas"] += 1
        monto = factura.total if fila.accion == "pagada" else fila.abonado
        if monto > 0 and not anulada:
            Pago.objects.create(
                factura=factura,
                fecha=(fila.fecha_cobro or fila.fecha_emision) if fila.origen == "Excel" else fila.fecha_emision,
                forma=Pago.Forma.OTRO,
                referencia=f"Importación {fila.origen}",
                monto=monto,
                notas=f"Estado al importar: «{fila.estado_origen or fila.accion}»",
                creado_por=usuario,
            )
            creados["pagos"] += 1
    return creados
