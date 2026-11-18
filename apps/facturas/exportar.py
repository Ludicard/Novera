"""Exporta facturas a Excel con el mismo orden de columnas que usaba el cliente, más pagado y saldo."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Estado

COLUMNAS = [
    ("Número de Factura", 22), ("Periodo", 10), ("Fecha", 12), ("Tipo", 10), ("Cliente", 34),
    ("RUC / Cédula", 15), ("Objeto", 40), ("Fecha Cobro", 12), ("Valor", 12), ("% IVA", 7),
    ("IVA", 11), ("TOTAL", 12), ("Pagado", 12), ("Saldo", 12), ("Estado", 14),
]
MONEDA = '"$"#,##0.00'


def exportar_facturas(facturas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Facturas"
    ws.append([c for c, _ in COLUMNAS])
    for i, (_, ancho) in enumerate(COLUMNAS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
        celda = ws.cell(1, i)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F4E5F")
    estados = dict(Estado.choices)
    for f in facturas:
        ws.append([
            f.numero, f.periodo.strftime("%m/%Y"), f.fecha_emision, f.get_tipo_display(),
            f.cliente.nombre if f.cliente else "", f.cliente.identificacion if f.cliente else "",
            f.objeto, f.fecha_cobro, f.subtotal, f.porcentaje_iva / 100, f.iva, f.total,
            f.pagado, f.saldo if not f.anulada else 0, estados.get(f.estado, f.estado),
        ])
    for fila in ws.iter_rows(min_row=2):
        fila[2].number_format = fila[7].number_format = "dd/mm/yyyy"
        fila[9].number_format = "0%"
        for celda in (fila[8], fila[10], fila[11], fila[12], fila[13]):
            celda.number_format = MONEDA
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()
