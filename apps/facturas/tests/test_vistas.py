import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.facturas.models import Factura, Pago


class VistasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("usuario", password="clave-segura-123")
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(nombre="Edificio Central", dias_credito=15)

    def datos_factura(self, **extra):
        hoy = timezone.localdate()
        datos = {
            "tipo": "FACTURA", "numero": "676", "cliente": self.cliente.pk, "periodo": hoy.strftime("%Y-%m"),
            "fecha_emision": hoy.isoformat(), "dias_credito": 15, "fecha_cobro": "",
            "objeto": "Mtto ascensor noviembre", "subtotal": "180", "porcentaje_iva": "15", "notas": "",
        }
        datos.update(extra)
        return datos

    def test_salud_sin_login(self):
        self.client.logout()
        r = self.client.get("/salud/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"ok")

    def test_requiere_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_paginas_cargan(self):
        for nombre in ["dashboard", "facturas:lista", "facturas:nueva", "facturas:importar", "clientes:lista", "clientes:nuevo"]:
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)

    def test_crear_factura_completa_numero_y_calcula(self):
        r = self.client.post(reverse("facturas:nueva"), self.datos_factura())
        f = Factura.objects.get()
        self.assertRedirects(r, f.get_absolute_url())
        self.assertEqual(f.numero, "001-001-000000676")
        self.assertEqual((f.iva, f.total), (Decimal("27.00"), Decimal("207.00")))
        self.assertEqual(f.fecha_cobro, f.fecha_emision + timedelta(days=15))
        self.assertEqual(f.creado_por, self.user)
        self.assertEqual(self.client.get(f.get_absolute_url()).status_code, 200)
        self.assertContains(self.client.get(reverse("facturas:nueva")), "001-001-000000677")

    def test_numero_duplicado(self):
        self.client.post(reverse("facturas:nueva"), self.datos_factura())
        r = self.client.post(reverse("facturas:nueva"), self.datos_factura())
        self.assertContains(r, "Ya existe")
        self.assertEqual(Factura.objects.count(), 1)

    def test_pagos_y_saldo(self):
        self.client.post(reverse("facturas:nueva"), self.datos_factura())
        f = Factura.objects.get()
        url = reverse("facturas:registrar_pago", args=[f.pk])
        base = {"fecha": timezone.localdate().isoformat(), "forma": "TRANSFERENCIA", "referencia": "123", "notas": ""}
        self.client.post(url, {**base, "monto": "100"})
        r = self.client.post(url, {**base, "monto": "500"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Pago.objects.count(), 1)
        self.assertEqual(Factura.objects.con_saldos().get().saldo, Decimal("107.00"))
        self.assertContains(self.client.get(reverse("facturas:lista") + "?estado=PARCIAL"), f.numero)

    def test_no_anula_con_pagos(self):
        self.client.post(reverse("facturas:nueva"), self.datos_factura())
        f = Factura.objects.get()
        Pago.objects.create(factura=f, monto=10)
        self.client.post(reverse("facturas:anular", args=[f.pk]), {"motivo": "error"})
        f.refresh_from_db()
        self.assertFalse(f.anulada)
        f.pagos.all().delete()
        self.client.post(reverse("facturas:anular", args=[f.pk]), {"motivo": "error"})
        f.refresh_from_db()
        self.assertTrue(f.anulada)

    def test_exportar(self):
        self.client.post(reverse("facturas:nueva"), self.datos_factura())
        r = self.client.get(reverse("facturas:exportar"))
        ws = openpyxl.load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws["A2"].value, "001-001-000000676")

    def test_importar_flujo_web(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Facturas"
        ws.append(["Numero de Factura", "Periodo", "Fecha", "Tipo", "Cliente", "Objeto", "Fecha Cobro", "Valor", "IVA", "TOTAL", "Estado"])
        ws.append(["001-001-000000500", "mayo", "20/05/2025", None, "edf central", "Mtto", None, 80, 12, 92, "No Pagada"])
        contenido = BytesIO()
        wb.save(contenido)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            archivo = SimpleUploadedFile("base.xlsx", contenido.getvalue())
            r = self.client.post(reverse("facturas:importar"), {"archivo": archivo, "estado_desconocido": "pendiente"})
            self.assertContains(r, "Vista previa")
            self.assertEqual(Factura.objects.count(), 0)
            r = self.client.post(reverse("facturas:importar"), {"accion": "confirmar"})
            self.assertRedirects(r, reverse("facturas:lista"))
        self.assertEqual(Factura.objects.get().cliente, self.cliente)
