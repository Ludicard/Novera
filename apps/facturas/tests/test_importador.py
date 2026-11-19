import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.test import TestCase

from apps.clientes.models import Cliente
from apps.facturas import importador as imp
from apps.facturas.models import Factura, Pago

ENCABEZADO = ["Numero de Factura", "Periodo", "Fecha", "Tipo", "Cliente", "Objeto",
              "Fecha Cobro", "Valor", "IVA", "TOTAL", "Estado"]


class NormalizadoresTests(TestCase):
    def test_decimal(self):
        self.assertEqual(imp.a_decimal("6508,91"), Decimal("6508.91"))
        self.assertEqual(imp.a_decimal("1.234,56"), Decimal("1234.56"))
        self.assertEqual(imp.a_decimal(109.756), Decimal("109.76"))
        self.assertIsNone(imp.a_decimal("#REF!"))
        self.assertIsNone(imp.a_decimal(None))

    def test_fecha(self):
        self.assertEqual(imp.a_fecha("19/8/2024"), date(2024, 8, 19))
        self.assertEqual(imp.a_fecha("8/21/2024"), date(2024, 8, 21))
        self.assertEqual(imp.a_fecha(datetime(2025, 3, 20)), date(2025, 3, 20))
        self.assertIsNone(imp.a_fecha("lunes 23 de nov"))

    def test_periodo(self):
        ref = date(2025, 3, 20)
        self.assertEqual(imp.a_periodo("Marzo", ref), date(2025, 3, 1))
        self.assertEqual(imp.a_periodo("julio - 2025", ref), date(2025, 7, 1))
        self.assertEqual(imp.a_periodo(datetime(2026, 2, 1), ref), date(2026, 2, 1))
        self.assertEqual(imp.a_periodo(None, ref), date(2025, 3, 1))
        self.assertEqual(imp.a_periodo("Diciembre", date(2025, 1, 10)), date(2024, 12, 1))

    def test_numero(self):
        self.assertEqual(imp.normalizar_numero(" 001-001-000000071")[:2], ("001-001-000000071", "FACTURA"))
        self.assertEqual(imp.normalizar_numero("Reibo 066")[:2], ("Recibo 066", "RECIBO"))
        self.assertEqual(imp.normalizar_numero("Recibo357")[:2], ("Recibo 357", "RECIBO"))
        self.assertFalse(imp.normalizar_numero("Sin factura")[2])

    def test_identificacion_recupera_cero_inicial(self):
        self.assertEqual(imp.normalizar_identificacion(400000004), "0400000004")
        self.assertEqual(imp.normalizar_identificacion(990000002001), "0990000002001")
        self.assertEqual(imp.normalizar_identificacion(1790000003001), "1790000003001")
        self.assertEqual(imp.normalizar_identificacion("N/A"), "")

    def test_clave_cliente(self):
        self.assertEqual(imp.clave_cliente("Edificio Central"), imp.clave_cliente("edf central"))
        self.assertEqual(imp.clave_cliente("EDF NORTE"), imp.clave_cliente("norte"))
        self.assertNotEqual(imp.clave_cliente("Torre Sur"), imp.clave_cliente("Torre Este"))

    def test_iva_12_incluido(self):
        sub, pct, iva, total, avisos = imp.inferir_montos(Decimal("100"), None, Decimal("112"))
        self.assertEqual((pct, iva, total, avisos), (Decimal("12"), Decimal("12.00"), Decimal("112"), []))

    def test_iva_15_explicito(self):
        self.assertEqual(imp.inferir_montos(Decimal("180"), Decimal("27"), Decimal("207"))[1], Decimal("15"))

    def test_sin_iva(self):
        self.assertEqual(imp.inferir_montos(Decimal("80"), None, Decimal("80"))[1:4], (Decimal("0"), Decimal("0.00"), Decimal("80")))

    def test_total_incoherente_avisa(self):
        avisos = imp.inferir_montos(Decimal("1800"), Decimal("274.5"), Decimal("631.35"))[4]
        self.assertTrue(avisos)


class ImportacionTests(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name) / "base.xlsx"
        wb = openpyxl.Workbook()
        altas = wb.active
        altas.title = "Altas"
        altas.append(["Cliente", "Ruc"])
        altas.append(["Edificio Central", 1790000001001])
        altas.append(["JUAN PEREZ", 400000004])
        ws = wb.create_sheet("Facturas")
        ws.append(ENCABEZADO)
        ws.append([" 001-001-000000071", "Enero", datetime(2024, 1, 12), None, "edf central", "Mtto", None, 100, None, 112, "#REF!"])
        ws.append(["001-001-000000072", "Enero", datetime(2024, 1, 12), None, "Torre Sur", "Mtto", "lunes 23 de nov", 140, 21, 161, "No Pagada"])
        ws.append(["001-001-000000073", "Enero", datetime(2024, 1, 17), None, "", "", None, None, None, None, "Anulada"])
        ws.append(["001-001-000000074", None, None, None, "JUAN PEREZ", "Reparación", None, 50, None, 50, "pagada"])
        ws.append(["001-001-000000075", None, None, None, None, None, None, None, None, None, None])
        ws.append(["001-001-000000072", "Febrero", datetime(2024, 2, 1), None, "Torre Sur", "Otro", None, 10, None, 10, "No Pagada"])
        wb.save(self.ruta)

    def tearDown(self):
        self.dir.cleanup()

    def test_analizar_y_aplicar(self):
        resultado = imp.analizar(self.ruta)
        self.assertEqual(resultado.errores, [])
        self.assertEqual(len(resultado.importables), 5)
        self.assertEqual(len(resultado.omitidas), 1)  # la 075 sin datos
        self.assertEqual(Factura.objects.count(), 0, "analizar no debe escribir")

        creados = imp.aplicar(resultado)
        self.assertEqual(creados, {"clientes": 3, "facturas": 5, "pagos": 1, "saltadas": 0})

        f71 = Factura.objects.get(numero="001-001-000000071")
        self.assertEqual(f71.cliente.nombre, "Edificio Central")
        self.assertEqual(f71.cliente.identificacion, "1790000001001")
        self.assertEqual((f71.porcentaje_iva, f71.iva), (Decimal("12.00"), Decimal("12.00")))
        self.assertFalse(f71.pagos.exists())

        self.assertTrue(Factura.objects.get(numero="001-001-000000073").anulada)
        f74 = Factura.objects.get(numero="001-001-000000074")
        self.assertEqual(f74.fecha_emision, date(2024, 1, 17))  # tomada de la fila anterior
        self.assertEqual(Pago.objects.get(factura=f74).monto, Decimal("50.00"))
        self.assertEqual(Cliente.objects.get(nombre="JUAN PEREZ").identificacion, "0400000004")
        self.assertIn("lunes 23 de nov", Factura.objects.get(numero="001-001-000000072").notas)
        self.assertTrue(Factura.objects.filter(numero="001-001-000000072 (dup 2)").exists())

    def test_reimportar_no_duplica(self):
        imp.aplicar(imp.analizar(self.ruta))
        segundo = imp.analizar(self.ruta)
        self.assertEqual(segundo.importables, [])
        self.assertEqual(imp.aplicar(segundo), {"clientes": 0, "facturas": 0, "pagos": 0, "saltadas": 0})

    def test_desconocidas_como_pagadas(self):
        imp.aplicar(imp.analizar(self.ruta, estado_desconocido="pagada"))
        self.assertTrue(Factura.objects.get(numero="001-001-000000071").pagos.exists())

    def test_archivo_sin_hoja_facturas(self):
        wb = openpyxl.Workbook()
        wb.save(self.ruta)
        self.assertTrue(imp.analizar(self.ruta).errores)


ENCABEZADO_FM = [
    "Fecha de emision", "No Factura", "Clave de acceso", "Base imponible IVA", "Base imponible 0%",
    "Base imponible 5%", "Base imponible 8%", "Base imponible no IVA", "IVA", "IVA 5%", "IVA 8%", "ICE",
    "Total descuento", "Valor total", "NID Cliente", "Cliente", "Estado", "Reembolso", "Por cobrar",
    "Saldo cobrar", "Cobrada", "Info. adicional", "Centro de costo", "Plazo", "Forma de Pago",
    "Valor de Pago", "Placa",
]


def fila_fm(fecha, numero, base, iva, total, ruc, cliente, info="", estado="Autorizado SRI",
            por_cobrar="NO", saldo=0.0, cobrada="N/A", plazo=0):
    clave = numero.replace("-", "").rjust(49, "0")
    return [fecha, numero, clave, base, 0.0, 0.0, 0.0, 0.0, iva, 0.0, 0.0, 0.0, 0.0, total, ruc, cliente,
            estado, "NO", por_cobrar, saldo, cobrada, info, None, plazo, "OTROS CON UTILIZACION DEL SISTEMA FINANCIERO",
            total, None]


def excel_facturero(filas):
    """Reporte de Factura como lo descarga FactureroMovil (datos ficticios)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte de Factura 2025-01-01 "
    ws.append(["FACTURERO MÓVIL"])
    ws.append(["REPORTE DE FACTURA 2025-01-01 _ 2025-12-31"])
    ws.append(["Fecha de generación: 2026-01-02 10:00:00"])
    ws.append(["Generado por: USUARIO DE PRUEBA"])
    ws.append([])
    ws.append(ENCABEZADO_FM)
    for f in filas:
        ws.append(f)
    ruta = Path(tempfile.mkdtemp()) / "reporte.xlsx"
    wb.save(ruta)
    return ruta


class FactureroMovilTests(TestCase):
    def setUp(self):
        self.ruta = excel_facturero([
            fila_fm("2025-01-07", "001-001-000000101", 759.0, 113.85, 872.85, "1790000001001", "EDIFICIO CENTRAL S.A.",
                    "Dirección: Av. Siempre Viva 123 | Email: admin@central.test otra@central.test | Mes del Servicio: Diciembre"),
            fila_fm("2025-02-10", "001-001-000000102", 100.0, 15.0, 115.0, "1790000001001", "Edificio Central",
                    "Dirección: Av. Siempre Viva 123 | Teléfonos: 0999999999 | Mes ddel Servicio: Febrero", plazo=15),
            fila_fm("2025-03-03", "001-001-000000103", 200.0, 30.0, 230.0, "0990000002001", "CONJUNTO NORTE",
                    "Mes del Servicio: Marzo | Ascensor: Numero 2", por_cobrar="SI", saldo=130.0),
            fila_fm("2025-03-04", "001-001-000000104", 50.0, 7.5, 57.5, "0990000002001", "CONJUNTO NORTE", cobrada="SI"),
            fila_fm("2025-03-05", "001-001-000000105", 80.0, 12.0, 92.0, "0990000002001", "CONJUNTO NORTE",
                    estado="Anulado"),
            fila_fm("2025-03-06", "001-001-000000106", 80.0, 12.0, 92.0, "0990000002001", "CONJUNTO NORTE",
                    estado="Devuelta"),
            fila_fm("2025-03-07", "001-001-000000101", 1.0, 0.15, 1.15, "0990000002001", "CONJUNTO NORTE"),
        ])

    def test_detecta_formato_y_normaliza(self):
        r = imp.analizar(self.ruta)
        self.assertEqual(r.formato, "FactureroMovil")
        self.assertEqual(r.errores, [])
        f = {x.numero: x for x in r.importables}
        self.assertEqual(set(f), {"001-001-000000101", "001-001-000000102", "001-001-000000103",
                                  "001-001-000000104", "001-001-000000105"})
        a = f["001-001-000000101"]
        self.assertEqual(a.periodo, date(2024, 12, 1))  # servicio de diciembre facturado en enero
        self.assertEqual((a.subtotal, a.porcentaje_iva, a.iva, a.total),
                         (Decimal("759.00"), Decimal("15"), Decimal("113.85"), Decimal("872.85")))
        self.assertEqual(a.email, "admin@central.test")
        self.assertEqual(a.direccion, "Av. Siempre Viva 123")
        self.assertEqual(a.objeto, "Mes del Servicio: Diciembre")
        self.assertEqual(f["001-001-000000102"].periodo, date(2025, 2, 1))  # errata en la clave
        self.assertEqual(f["001-001-000000102"].dias_credito, 15)
        self.assertEqual(f["001-001-000000103"].abonado, Decimal("100.00"))
        self.assertEqual(f["001-001-000000104"].accion, "pagada")
        self.assertEqual(f["001-001-000000105"].accion, "anulada")
        omitidas = {x.numero: x.avisos for x in r.omitidas}
        self.assertIn("no está autorizada", omitidas["001-001-000000106"][0])
        self.assertEqual(r.resumen()["clientes_nuevos"], 2)

    def test_aplicar_crea_clientes_por_ruc_y_pagos(self):
        imp.aplicar(imp.analizar(self.ruta, estado_desconocido="pendiente"))
        self.assertEqual(Cliente.objects.count(), 2)  # «EDIFICIO CENTRAL S.A.» y «Edificio Central» (mismo RUC)
        central = Cliente.objects.get(identificacion="1790000001001")
        self.assertEqual((central.email, central.telefono), ("admin@central.test", "0999999999"))
        hoy = date(2025, 3, 10)
        estados = {f.numero: f.estado for f in Factura.objects.con_saldos(hoy)}
        self.assertEqual(estados["001-001-000000103"], "PARCIAL")
        self.assertEqual(estados["001-001-000000104"], "PAGADA")
        self.assertEqual(estados["001-001-000000105"], "ANULADA")
        self.assertEqual(Factura.objects.get(numero="001-001-000000102").fecha_cobro, date(2025, 2, 25))
        self.assertEqual(len(Factura.objects.get(numero="001-001-000000101").clave_acceso), 49)
        # Reimportar no duplica
        r = imp.analizar(self.ruta)
        self.assertEqual(r.importables, [])

    def test_estado_desconocido_pagada(self):
        imp.aplicar(imp.analizar(self.ruta, estado_desconocido="pagada"))
        self.assertEqual(Pago.objects.get(factura__numero="001-001-000000101").monto, Decimal("872.85"))

    def test_archivo_sin_formato(self):
        wb = openpyxl.Workbook()
        wb.active.append(["algo", "otra cosa"])
        ruta = Path(tempfile.mkdtemp()) / "x.xlsx"
        wb.save(ruta)
        self.assertIn("No se reconoce el formato", imp.analizar(ruta).errores[0])


def crear_excel(filas):
    """Excel histórico mínimo (hoja «Facturas»)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Facturas"
    ws.append(ENCABEZADO)
    for f in filas:
        ws.append(f)
    ruta = Path(tempfile.mkdtemp()) / "base.xlsx"
    wb.save(ruta)
    return ruta


class DuplicadosTests(TestCase):
    def reporte(self, numeros, clave=None):
        filas = []
        for n in numeros:
            fila = fila_fm("2025-03-03", f"001-001-{n:09d}", 100.0, 15.0, 115.0, "1790000001001", "EDIFICIO CENTRAL")
            fila[2] = clave or f"{n:049d}"
            filas.append(fila)
        return excel_facturero(filas)

    def test_clave_numero(self):
        from apps.facturas.models import clave_numero
        self.assertEqual(clave_numero("676"), "001-001-000000676")
        self.assertEqual(clave_numero("001-001-676"), "001-001-000000676")
        self.assertEqual(clave_numero(" 001-001-000000676 "), "001-001-000000676")
        self.assertEqual(clave_numero("Recibo  066"), "recibo 066")

    def test_reimportar_el_mismo_archivo(self):
        ruta = self.reporte([101, 102, 103])
        imp.aplicar(imp.analizar(ruta))
        r = imp.analizar(ruta)
        self.assertEqual(r.importables, [])
        self.assertEqual(r.resumen()["ya_existen"], 3)
        self.assertEqual(Factura.objects.count(), 3)

    def test_archivos_que_se_solapan(self):
        imp.aplicar(imp.analizar(self.reporte([101, 102, 103])))
        r = imp.analizar(self.reporte([102, 103, 104, 105]))
        self.assertEqual([f.numero for f in r.importables], ["001-001-000000104", "001-001-000000105"])
        imp.aplicar(r)
        self.assertEqual(Factura.objects.count(), 5)

    def test_numero_escrito_distinto_ya_existente(self):
        Factura.objects.create(numero="101", periodo=date(2025, 3, 1), fecha_emision=date(2025, 3, 3),
                               subtotal=100, total=115)
        r = imp.analizar(self.reporte([101, 102]))
        self.assertEqual([f.numero for f in r.importables], ["001-001-000000102"])

    def test_misma_clave_de_acceso_con_otro_numero(self):
        imp.aplicar(imp.analizar(self.reporte([101], clave="9" * 49)))
        self.assertEqual(imp.analizar(self.reporte([555], clave="9" * 49)).importables, [])

    def test_repetida_dentro_del_archivo(self):
        r = imp.analizar(self.reporte([101, 101]))
        self.assertEqual(len(r.importables), 1)
        self.assertIn("Repetida en el archivo", r.omitidas[0].avisos)

    def test_confirmar_dos_veces_no_duplica(self):
        r = imp.analizar(self.reporte([101, 102]))
        imp.aplicar(r)
        segunda = imp.aplicar(r)  # misma vista previa confirmada otra vez
        self.assertEqual((segunda["facturas"], segunda["saltadas"]), (0, 2))
        self.assertEqual(Factura.objects.count(), 2)

    def test_historico_y_luego_facturero(self):
        imp.aplicar(imp.analizar(crear_excel([
            ["001-001-000000101", "Marzo", date(2025, 3, 3), "Factura", "Edificio Central", "Mtto",
             None, 100, 15, 115, "No Pagada"],
        ])))
        r = imp.analizar(self.reporte([101, 102]))
        self.assertEqual([f.numero for f in r.importables], ["001-001-000000102"])
