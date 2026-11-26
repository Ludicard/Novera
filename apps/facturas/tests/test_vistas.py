import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.usuarios.tests.utils import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.usuarios.tests.utils import entrar_como
from apps.facturas.models import Factura, Pago


class VistasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("usuario", password="clave-segura-123")
        entrar_como(self.client, self.user, "administrador")
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

    def test_paginas_con_datos(self):
        self.client.post(reverse("facturas:nueva"), self.datos_factura())
        factura = Factura.objects.get()
        self.client.post(
            reverse("facturas:registrar_pago", args=[factura.pk]),
            {"fecha": timezone.localdate().isoformat(), "forma": "TRANSFERENCIA", "monto": "50", "referencia": "", "notas": ""},
        )
        self.assertEqual(factura.pagos.count(), 1)
        urls = [
            reverse("dashboard"),
            reverse("facturas:lista"),
            reverse("facturas:lista") + "?estado=ABIERTAS&q=central",
            reverse("facturas:lista") + f"?estado=PARCIAL&cliente={self.cliente.pk}",
            reverse("facturas:detalle", args=[factura.pk]),
            reverse("facturas:editar", args=[factura.pk]),
            reverse("facturas:exportar"),
            reverse("clientes:lista"),
            reverse("clientes:detalle", args=[self.cliente.pk]),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

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


class PanelTests(TestCase):
    def setUp(self):
        from datetime import date
        self.user = User.objects.create_user("usuario", password="clave-segura-123")
        entrar_como(self.client, self.user, "administrador")
        self.cliente = Cliente.objects.create(nombre="Edificio Central")
        self.hoy = date(2025, 6, 15)
        def factura(numero, emision, total, dias=30):
            return Factura.objects.create(
                numero=numero, cliente=self.cliente, periodo=emision, fecha_emision=emision,
                dias_credito=dias, subtotal=total, porcentaje_iva=0, iva=0, total=total,
            )
        self.f1 = factura("001-001-000000001", date(2025, 1, 10), Decimal("100.00"))  # vencida > 90
        self.f2 = factura("001-001-000000002", date(2025, 6, 1), Decimal("200.00"))   # por vencer
        self.f3 = factura("001-001-000000003", date(2025, 5, 2), Decimal("50.00"))    # pagada
        Pago.objects.create(factura=self.f3, fecha=date(2025, 5, 12), monto=Decimal("50.00"))
        factura("001-001-000000004", date(2024, 12, 1), Decimal("999.00"))           # fuera del año

    def test_datos_del_panel(self):
        from django.http import QueryDict
        from apps.facturas.dashboard import datos_panel
        d = datos_panel(QueryDict("periodo=anio"), self.hoy)
        k = d["kpis"]
        self.assertEqual(k["facturado"], Decimal("350.00"))
        self.assertEqual(k["cobrado"], Decimal("50.00"))
        self.assertEqual(k["por_cobrar"], Decimal("300.00"))
        self.assertEqual(k["vencido"], Decimal("100.00"))
        self.assertEqual(k["tasa_cobro"], 14)
        self.assertEqual(k["dias_cobro"], 10)
        tramos = {t["tramo"]: t["monto"] for t in d["graficos"]["tramos"]}
        self.assertEqual(tramos["Por vencer"], 200.0)
        self.assertEqual(tramos["Más de 90"], 100.0)
        self.assertEqual(len(d["mensual"]), 6)
        self.assertEqual(d["mensual"][4]["cobrado"], 50.0)  # mayo
        self.assertIn("emitida_desde=2025-01-01", d["filtro_lista"])

    def test_panel_responde_con_filtros(self):
        for q in ["", "?periodo=mes", "?periodo=todo", "?periodo=anio_anterior",
                  f"?periodo=rango&desde=2025-01-01&hasta=2025-03-31&cliente={self.cliente.pk}", "?periodo=raro"]:
            r = self.client.get(reverse("dashboard") + q)
            self.assertEqual(r.status_code, 200, q)
            self.assertContains(r, 'id="datos-panel"')

    def test_panel_vacio(self):
        Pago.objects.all().delete()
        Factura.objects.all().delete()
        self.assertContains(self.client.get(reverse("dashboard")), "Importar de FactureroMovil")

    def test_lista_filtra_por_emision(self):
        r = self.client.get(reverse("facturas:lista") + "?emitida_desde=2025-05-01&emitida_hasta=2025-06-30")
        self.assertEqual(r.context["pagina"].paginator.count, 2)


class ListadoTests(TestCase):
    def setUp(self):
        from datetime import date
        self.user = User.objects.create_user("usuario", password="clave-segura-123")
        entrar_como(self.client, self.user, "administrador")
        self.cliente = Cliente.objects.create(nombre="Edificio Central")
        hoy = timezone.localdate()
        def factura(n, total, dias_atras):
            emision = hoy - timedelta(days=dias_atras)
            return Factura.objects.create(
                numero=f"001-001-{n:09d}", cliente=self.cliente, periodo=emision, fecha_emision=emision,
                dias_credito=30, subtotal=total, porcentaje_iva=0, iva=0, total=total,
            )
        self.vencida = factura(676, Decimal("100.00"), 60)
        self.al_dia = factura(677, Decimal("200.00"), 5)
        self.pagada = factura(678, Decimal("50.00"), 10)
        Pago.objects.create(factura=self.pagada, monto=Decimal("50.00"))
        self.url = reverse("facturas:lista")

    def test_pestanas_y_conteos(self):
        r = self.client.get(self.url + "?periodo=todo")
        conteos = {p["clave"]: p["n"] for p in r.context["pestanas"]}
        self.assertEqual(conteos[""], 3)
        self.assertEqual(conteos["ABIERTAS"], 2)
        self.assertEqual(conteos["VENCIDA"], 1)
        self.assertEqual(conteos["PAGADA"], 1)
        r = self.client.get(self.url + "?estado=VENCIDA")
        self.assertEqual([f.pk for f in r.context["pagina"]], [self.vencida.pk])

    def test_orden_y_busqueda(self):
        r = self.client.get(self.url + "?periodo=todo&orden=-total")
        self.assertEqual([f.pk for f in r.context["pagina"]], [self.al_dia.pk, self.vencida.pk, self.pagada.pk])
        r = self.client.get(self.url + "?orden=no-existe")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(self.url + "?periodo=todo&q=676")
        self.assertEqual([f.pk for f in r.context["pagina"]], [self.vencida.pk])

    def test_cobro_rapido_vuelve_al_listado(self):
        volver = self.url + "?estado=ABIERTAS"
        r = self.client.post(reverse("facturas:registrar_pago", args=[self.al_dia.pk]), {
            "fecha": timezone.localdate().isoformat(), "forma": "TRANSFERENCIA", "monto": "200",
            "referencia": "", "notas": "", "siguiente": volver,
        })
        self.assertRedirects(r, volver)
        self.assertEqual(self.al_dia.pagos.count(), 1)

    def test_cobro_rapido_no_redirige_fuera(self):
        r = self.client.post(reverse("facturas:registrar_pago", args=[self.al_dia.pk]), {
            "fecha": timezone.localdate().isoformat(), "forma": "TRANSFERENCIA", "monto": "10",
            "referencia": "", "notas": "", "siguiente": "https://malicioso.test/",
        })
        self.assertEqual(r.url, self.al_dia.get_absolute_url())

    def test_cobro_rapido_con_error_avisa(self):
        r = self.client.post(reverse("facturas:registrar_pago", args=[self.al_dia.pk]), {
            "fecha": timezone.localdate().isoformat(), "forma": "TRANSFERENCIA", "monto": "999",
            "referencia": "", "notas": "", "siguiente": self.url,
        }, follow=True)
        self.assertContains(r, "No se registró el pago")
        self.assertEqual(self.al_dia.pagos.count(), 0)

    def test_cobrar_en_lote(self):
        ids = f"{self.vencida.pk},{self.al_dia.pk},{self.pagada.pk}"
        r = self.client.post(reverse("facturas:cobrar_lote"), {
            "ids": ids, "fecha": timezone.localdate().isoformat(), "forma": "DEPOSITO", "referencia": "Dep 1",
            "siguiente": self.url,
        })
        self.assertRedirects(r, self.url)
        estados = {f.pk: f.estado for f in Factura.objects.con_saldos()}
        self.assertTrue(all(e == "PAGADA" for e in estados.values()))
        self.assertEqual(Pago.objects.count(), 3)  # la ya pagada no recibe otro pago

    def test_exportar_seleccionadas(self):
        r = self.client.get(reverse("facturas:exportar") + f"?ids={self.vencida.pk},{self.al_dia.pk}")
        wb = openpyxl.load_workbook(BytesIO(r.content))
        self.assertEqual(wb.active.max_row, 3)  # encabezado + 2

    def test_numero_manual_duplicado_en_otra_forma(self):
        r = self.client.post(reverse("facturas:nueva"), {
            "tipo": "FACTURA", "numero": "001-001-676", "cliente": self.cliente.pk,
            "periodo": timezone.localdate().strftime("%Y-%m"), "fecha_emision": timezone.localdate().isoformat(),
            "dias_credito": 30, "fecha_cobro": "", "objeto": "x", "subtotal": "10", "porcentaje_iva": "15", "notas": "",
        })
        self.assertContains(r, "Ya existe el documento 001-001-000000676")


class CorreccionesRevisionTests(TestCase):
    """Errores encontrados en la revisión del flujo de Administrador."""

    def setUp(self):
        self.user = User.objects.create_superuser("jefe", "j@x.test", "clave-segura-123")
        entrar_como(self.client, self.user, "administrador")
        self.cliente = Cliente.objects.create(nombre="Edificio Central", identificacion="1790000001001")
        hoy = timezone.localdate()
        self.f = Factura.objects.create(
            numero="001-001-000000900", cliente=self.cliente, periodo=hoy, fecha_emision=hoy - timedelta(days=40),
            dias_credito=30, subtotal=Decimal("100"), porcentaje_iva=Decimal("15"), iva=Decimal("15"), total=Decimal("115"),
        )

    def test_cliente_invalido_en_nueva_factura(self):
        self.assertEqual(self.client.get(reverse("facturas:nueva") + "?cliente=abc").status_code, 200)

    def test_cliente_inactivo_queda_elegido(self):
        self.cliente.activo = False
        self.cliente.save()
        r = self.client.get(reverse("facturas:nueva") + f"?cliente={self.cliente.pk}")
        self.assertIn(self.cliente, r.context["form"].fields["cliente"].queryset)
        self.assertContains(r, "inactivo")

    def test_no_se_puede_editar_por_debajo_de_lo_cobrado(self):
        Pago.objects.create(factura=self.f, monto=Decimal("50"))
        r = self.client.post(reverse("facturas:editar", args=[self.f.pk]), {
            "tipo": "FACTURA", "numero": self.f.numero, "cliente": self.cliente.pk, "periodo": self.f.periodo.strftime("%Y-%m"),
            "fecha_emision": self.f.fecha_emision.isoformat(), "dias_credito": 30, "fecha_cobro": "",
            "objeto": "", "subtotal": "10", "porcentaje_iva": "15", "notas": "",
        })
        self.assertContains(r, "sería menor que lo ya cobrado")
        self.f.refresh_from_db()
        self.assertEqual(self.f.total, Decimal("115"))

    def test_admin_recalcula_montos_y_valida_pagos(self):
        r = self.client.post(reverse("admin:facturas_pago_add"), {
            "factura": self.f.pk, "fecha": timezone.localdate().isoformat(), "forma": "OTRO", "monto": "500",
            "referencia": "", "notas": "",
        })
        self.assertContains(r, "supera el saldo pendiente")
        self.assertEqual(self.client.get(reverse("admin:facturas_factura_changelist")).status_code, 200)

    def test_anular_dos_veces(self):
        self.client.post(reverse("facturas:anular", args=[self.f.pk]), {"motivo": "Error"})
        self.client.post(reverse("facturas:anular", args=[self.f.pk]), {"motivo": "Otra vez"})
        self.f.refresh_from_db()
        self.assertEqual(self.f.motivo_anulacion, "Error")

    def test_cliente_nuevo_sin_redireccion_externa(self):
        r = self.client.post(reverse("clientes:nuevo") + "?next=https://malicioso.test/", {
            "nombre": "Torre Sur", "identificacion": "", "email": "", "telefono": "", "direccion": "",
            "dias_credito": 30, "activo": "on", "notas": "",
        })
        self.assertFalse(r.url.startswith("http"))

    def test_ruc_duplicado(self):
        r = self.client.post(reverse("clientes:nuevo"), {
            "nombre": "Otro nombre", "identificacion": "1790000001001", "email": "", "telefono": "",
            "direccion": "", "dias_credito": 30, "activo": "on", "notas": "",
        })
        self.assertContains(r, "ya es del cliente")

    def test_cliente_rapido_desde_la_factura(self):
        r = self.client.post(reverse("clientes:rapido"), {"nombre": "Torre Norte", "identificacion": "", "email": "", "dias_credito": 15})
        self.assertEqual(r.json()["dias_credito"], 15)
        r = self.client.post(reverse("clientes:rapido"), {"nombre": "torre norte", "identificacion": "", "email": "", "dias_credito": 15})
        self.assertEqual(r.status_code, 400)

    def test_cobrar_todas_las_filtradas_con_fecha_de_vencimiento(self):
        hoy = timezone.localdate()
        for n in range(901, 904):
            Factura.objects.create(
                numero=f"001-001-{n:09d}", cliente=self.cliente, periodo=hoy, fecha_emision=hoy - timedelta(days=60),
                dias_credito=30, subtotal=Decimal("10"), porcentaje_iva=0, iva=0, total=Decimal("10"),
            )
        r = self.client.post(reverse("facturas:cobrar_lote"), {
            "todas": "1", "filtros": "estado=VENCIDA", "fecha_modo": "vencimiento", "forma": "OTRO", "referencia": "",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Pago.objects.count(), 4)
        pago = Pago.objects.get(factura=self.f)
        self.assertEqual(pago.fecha, self.f.fecha_cobro)

    def test_filtro_invalido_no_anula_los_demas(self):
        r = self.client.get(reverse("facturas:lista") + "?estado=VENCIDA&desde=2025-13")
        self.assertEqual(r.context["pagina"].paginator.count, 1)



class PeriodoListadoTests(TestCase):
    """El listado arranca en el mes actual; las pestañas de cobro muestran todo lo pendiente."""

    def setUp(self):
        from datetime import date

        from apps.facturas.views import _mover_mes
        user = User.objects.create_user("usuario", password="clave-segura-123")
        entrar_como(self.client, user, "administrador")
        cliente = Cliente.objects.create(nombre="Edificio Central")
        hoy = timezone.localdate()
        self.este_mes = hoy.replace(day=1)
        self.mes_anterior = _mover_mes(self.este_mes, -1)
        self.hace_un_anio = _mover_mes(self.este_mes, -12)

        def factura(n, emision, dias=30):
            return Factura.objects.create(
                numero=f"001-001-{n:09d}", cliente=cliente, periodo=emision, fecha_emision=emision, dias_credito=dias,
                subtotal=Decimal("100"), porcentaje_iva=0, iva=0, total=Decimal("100"),
            )
        self.actual = factura(1, self.este_mes)
        self.anterior = factura(2, self.mes_anterior)
        self.vieja = factura(3, self.hace_un_anio)  # vencida hace casi un año
        self.url = reverse("facturas:lista")

    def numeros(self, query=""):
        r = self.client.get(self.url + query)
        return sorted(f.numero[-1] for f in r.context["pagina"]), r

    def test_por_defecto_este_mes(self):
        nums, r = self.numeros()
        self.assertEqual(nums, ["1"])
        self.assertEqual(r.context["periodo"]["clave"], "mes")

    def test_navegar_meses(self):
        nums, r = self.numeros(f"?periodo={self.mes_anterior:%Y-%m}")
        self.assertEqual(nums, ["2"])
        self.assertEqual(r.context["periodo"]["clave"], "mes_anterior")
        self.assertEqual(r.context["periodo"]["siguiente"], f"{self.este_mes:%Y-%m}")
        _, r = self.numeros()
        self.assertIsNone(r.context["periodo"]["siguiente"])  # no se navega al futuro

    def test_vencidas_muestra_todo_el_historial(self):
        nums, r = self.numeros("?estado=VENCIDA")
        self.assertIn("3", nums)
        conteos = {p["clave"]: p["n"] for p in r.context["pestanas"]}
        self.assertEqual(conteos[""], 1)          # «Todas»: este mes
        self.assertGreaterEqual(conteos["VENCIDA"], 1)  # vencidas: de cualquier mes
        # Si se elige un periodo, se respeta también en la pestaña de vencidas
        nums, _ = self.numeros("?estado=VENCIDA&periodo=mes")
        self.assertNotIn("3", nums)

    def test_periodos_rapidos_y_todo(self):
        self.assertEqual(self.numeros("?periodo=todo")[0], ["1", "2", "3"])
        self.assertEqual(self.numeros("?periodo=3m")[0], ["1", "2"])
        self.assertEqual(self.numeros("?periodo=inventado")[0], ["1", "2", "3"])  # desconocido → todo

    def test_rango_explicito_manda_sobre_el_periodo(self):
        nums, r = self.numeros(f"?periodo=mes&emitida_desde={self.hace_un_anio:%Y-%m-%d}&emitida_hasta={self.hace_un_anio:%Y-%m-%d}")
        self.assertEqual(nums, ["3"])
        self.assertEqual(r.context["periodo"]["clave"], "rango")

    def test_buscar_sin_periodo_busca_en_todo_el_historial(self):
        self.assertEqual(self.numeros("?q=000000003")[0], ["3"])

    def test_exportar_respeta_el_periodo(self):
        r = self.client.get(reverse("facturas:exportar") + "?periodo=mes")
        wb = openpyxl.load_workbook(BytesIO(r.content))
        self.assertEqual(wb.active.max_row, 2)

    def test_sin_facturas_en_el_mes_ofrece_todo_el_historial(self):
        r = self.client.get(self.url + "?periodo=2001-01")
        self.assertContains(r, "Buscar en todo el historial")
