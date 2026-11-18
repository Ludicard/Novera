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
        self.assertEqual(creados, {"clientes": 3, "facturas": 5, "pagos": 1})

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
        self.assertEqual(imp.aplicar(segundo), {"clientes": 0, "facturas": 0, "pagos": 0})

    def test_desconocidas_como_pagadas(self):
        imp.aplicar(imp.analizar(self.ruta, estado_desconocido="pagada"))
        self.assertTrue(Factura.objects.get(numero="001-001-000000071").pagos.exists())

    def test_archivo_sin_hoja_facturas(self):
        wb = openpyxl.Workbook()
        wb.save(self.ruta)
        self.assertTrue(imp.analizar(self.ruta).errores)
