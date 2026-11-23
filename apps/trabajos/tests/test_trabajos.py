from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Equipo
from apps.facturas.models import Factura
from apps.trabajos.models import Informe, OrdenTrabajo, Proforma, Recurso
from apps.usuarios.roles import ADMINISTRADOR, MANAGER, TECNICO, asignar_roles, roles_de
from apps.usuarios.tests.utils import entrar_como

CLAVE = "clave-segura-123"


def lineas(*filas, prefijo="lineas", iniciales=0):
    datos = {f"{prefijo}-TOTAL_FORMS": str(len(filas)), f"{prefijo}-INITIAL_FORMS": str(iniciales),
             f"{prefijo}-MIN_NUM_FORMS": "0", f"{prefijo}-MAX_NUM_FORMS": "1000"}
    for i, f in enumerate(filas):
        for k, v in f.items():
            datos[f"{prefijo}-{i}-{k}"] = v
    return datos


def datos_orden(cliente, **extra):
    d = {"cliente": cliente.pk, "titulo": "Mantenimiento", "ubicacion": "", "horas_estimadas": "", "fecha_inicio": "",
         "fecha_fin": "", "instrucciones": "", "descripcion": "", "notas": ""}
    d.update(lineas(prefijo="recursos"))
    d.update(extra)
    return d


class Base(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Edificio Central", direccion="Av. Siempre Viva 123")
        self.tec = User.objects.create_user("luis", password=CLAVE, first_name="Luis")
        asignar_roles(self.tec, [TECNICO])


class ProformasYOrdenesTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user("jefa", password=CLAVE, first_name="Jefa")
        entrar_como(self.client, self.admin, ADMINISTRADOR)

    def crear_proforma(self):
        datos = {"cliente": self.cliente.pk, "titulo": "Cambio de cables del ascensor", "fecha": timezone.localdate().isoformat(),
                 "validez_dias": 15, "porcentaje_iva": "15", "descripcion": "", "notas": ""}
        datos.update(lineas(
            {"tipo": "SERVICIO", "descripcion": "Mano de obra", "cantidad": "8", "unidad": "h", "precio_unitario": "25"},
            {"tipo": "MATERIAL", "descripcion": "Cable de acero 10 mm", "cantidad": "30", "unidad": "m", "precio_unitario": "4.5"},
        ))
        r = self.client.post(reverse("trabajos:proforma_nueva"), datos)
        self.assertEqual(r.status_code, 302)
        return Proforma.objects.get()

    def test_proforma_totales_y_aprobacion_genera_orden(self):
        p = self.crear_proforma()
        self.assertEqual((p.numero, p.subtotal, p.total), ("PF-00001", Decimal("335.00"), Decimal("385.25")))
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "aprobar"})
        orden = OrdenTrabajo.objects.get()
        self.assertEqual((orden.numero, orden.proforma, orden.ubicacion), ("OT-00001", p, "Av. Siempre Viva 123"))
        self.assertEqual(list(orden.recursos.values_list("descripcion", flat=True)), ["Cable de acero 10 mm"])
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "aprobar"})
        self.assertEqual(OrdenTrabajo.objects.count(), 1)

    def test_orden_con_tecnicos_equipos_y_herramientas(self):
        equipo = Equipo.objects.create(cliente=self.cliente, nombre="Ascensor 1")
        d = datos_orden(self.cliente, tecnicos=[self.tec.pk], equipos=[equipo.pk], instrucciones="Luis: cambiar cables",
                        fecha_inicio="2026-12-01", fecha_fin="2026-12-03", horas_estimadas="12")
        d.update(lineas({"tipo": "HERRAMIENTA", "descripcion": "Taladro", "cantidad": "1", "unidad": "u"}, prefijo="recursos"))
        r = self.client.post(reverse("trabajos:orden_nueva"), d)
        orden = OrdenTrabajo.objects.get()
        self.assertRedirects(r, orden.get_absolute_url())
        self.assertEqual(list(orden.tecnicos.all()), [self.tec])
        self.assertEqual(list(orden.equipos.all()), [equipo])
        self.assertEqual(orden.recursos.get().tipo, Recurso.Tipo.HERRAMIENTA)
        self.assertContains(self.client.get(equipo.get_absolute_url()), orden.numero)  # historial del equipo

    def test_equipo_de_otro_cliente_no_se_acepta(self):
        otro = Cliente.objects.create(nombre="Torre Norte")
        ajeno = Equipo.objects.create(cliente=otro, nombre="Montacargas")
        r = self.client.post(reverse("trabajos:orden_nueva"), datos_orden(self.cliente, equipos=[ajeno.pk]))
        self.assertContains(r, "es de otro cliente")

    def test_fin_antes_del_inicio(self):
        r = self.client.post(reverse("trabajos:orden_nueva"), datos_orden(self.cliente, fecha_inicio="2026-12-05", fecha_fin="2026-12-01"))
        self.assertContains(r, "no puede ser anterior al inicio")

    def test_factura_o_recibo_con_varias_ordenes(self):
        o1 = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Uno")
        o2 = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Dos")
        hoy = timezone.localdate()
        base = {"cliente": self.cliente.pk, "periodo": hoy.strftime("%Y-%m"), "fecha_emision": hoy.isoformat(),
                "dias_credito": 30, "fecha_cobro": "", "objeto": "Trabajos", "subtotal": "100", "porcentaje_iva": "15", "notas": ""}
        r = self.client.post(reverse("facturas:nueva"), {**base, "tipo": "RECIBO", "numero": "", "ordenes": [o1.pk, o2.pk]})
        recibo = Factura.objects.get()
        self.assertEqual((recibo.tipo, recibo.numero), ("RECIBO", "REC-00001"))
        self.assertEqual(set(recibo.ordenes.all()), {o1, o2})
        self.assertContains(self.client.get(o1.get_absolute_url()), "REC-00001")
        # Una orden de otro cliente no se puede incluir
        otro = Cliente.objects.create(nombre="Torre Norte")
        ajena = OrdenTrabajo.objects.create(cliente=otro, titulo="Ajena")
        r = self.client.post(reverse("facturas:nueva"), {**base, "tipo": "FACTURA", "numero": "", "ordenes": [ajena.pk]})
        self.assertContains(r, "es de otro cliente")

    def test_facturar_desde_la_orden_precarga_datos(self):
        o = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Reparación")
        r = self.client.get(reverse("facturas:nueva") + f"?orden={o.pk}")
        self.assertEqual(r.context["form"].initial["ordenes"], [o])
        self.assertEqual(r.context["form"].initial["cliente"], self.cliente)


class InformesTests(Base):
    def setUp(self):
        super().setUp()
        self.orden = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Revisión")
        self.orden.tecnicos.add(self.tec)
        self.ajena = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Ajena")
        entrar_como(self.client, self.tec, TECNICO)

    def test_generar_informe_y_terminar_la_orden(self):
        r = self.client.post(reverse("trabajos:informes"), {
            "orden": self.orden.pk, "fecha": timezone.localdate().isoformat(), "horas_trabajadas": "3",
            "trabajo_realizado": "Cambio de cables", "materiales_usados": "30 m cable", "observaciones": "",
        })
        self.assertRedirects(r, reverse("trabajos:informes"))
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, OrdenTrabajo.Estado.EN_CURSO)
        self.client.post(reverse("trabajos:informes"), {
            "orden": self.orden.pk, "fecha": timezone.localdate().isoformat(), "trabajo_realizado": "Pruebas OK",
            "trabajo_terminado": "on",
        })
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, OrdenTrabajo.Estado.TERMINADA)
        self.assertEqual(Informe.objects.filter(tecnico=self.tec).count(), 2)

    def test_no_puede_informar_ordenes_ajenas(self):
        r = self.client.post(reverse("trabajos:informes"), {
            "orden": self.ajena.pk, "fecha": timezone.localdate().isoformat(), "trabajo_realizado": "X",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Informe.objects.exists())

    def test_tecnico_ve_solo_sus_ordenes(self):
        r = self.client.get(reverse("trabajos:ordenes"))
        self.assertEqual([o.titulo for o in r.context["pagina"]], ["Revisión"])
        self.assertEqual(self.client.get(self.orden.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.ajena.get_absolute_url()).status_code, 404)


class TecnicosYEquiposTests(Base):
    def setUp(self):
        super().setUp()
        self.mana = User.objects.create_user("mana", password=CLAVE)
        entrar_como(self.client, self.mana, MANAGER)

    def test_manager_crea_tecnico(self):
        r = self.client.post(reverse("trabajos:tecnico_nuevo"), {
            "first_name": "Ana", "last_name": "", "username": "ana", "email": "",
            "password1": "Clave-Segura-987", "password2": "Clave-Segura-987",
        })
        self.assertRedirects(r, reverse("trabajos:tecnicos"))
        self.assertEqual(roles_de(User.objects.get(username="ana")), [TECNICO])

    def test_manager_no_edita_cuentas_con_otros_roles(self):
        jefa = User.objects.create_user("jefa", password=CLAVE)
        asignar_roles(jefa, [ADMINISTRADOR, TECNICO])
        self.assertRedirects(self.client.get(reverse("trabajos:tecnico_editar", args=[jefa.pk])), reverse("trabajos:tecnicos"))
        self.assertEqual(self.client.get(reverse("trabajos:tecnico_editar", args=[self.tec.pk])).status_code, 200)

    def test_equipos_crud(self):
        r = self.client.post(reverse("clientes:equipo_nuevo"), {
            "cliente": self.cliente.pk, "tipo": "ASCENSOR", "nombre": "Ascensor 1", "marca": "Otis", "modelo": "Gen2",
            "numero_serie": "", "ubicacion": "Torre A", "capacidad": "", "fecha_instalacion": "", "activo": "on", "notas": "",
        })
        e = Equipo.objects.get()
        self.assertRedirects(r, e.get_absolute_url())
        r = self.client.post(reverse("clientes:equipo_nuevo"), {"cliente": self.cliente.pk, "tipo": "ASCENSOR", "nombre": "ascensor 1"})
        self.assertContains(r, "ya tiene un equipo con ese nombre")
        r = self.client.get(reverse("clientes:equipos") + "?q=otis")
        self.assertEqual(list(r.context["pagina"]), [e])
        self.assertContains(self.client.get(self.cliente.get_absolute_url()), "Ascensor 1")


class MenusYPermisosTests(Base):
    def titulos(self):
        return [m["titulo"] for m in self.client.get(reverse("inicio")).context["mosaicos"]]

    def test_menu_administrador(self):
        entrar_como(self.client, User.objects.create_user("jefa", password=CLAVE), ADMINISTRADOR)
        self.assertEqual(self.titulos(), [
            "Administrar proformas", "Administrar órdenes de trabajo", "Generar factura o recibo", "Cargar pagos",
            "Revisar datos financieros",
        ])
        for m in self.client.get(reverse("inicio")).context["mosaicos"]:
            self.assertEqual(self.client.get(m["url"]).status_code, 200, m["url"])

    def test_menu_manager_y_sus_limites(self):
        entrar_como(self.client, User.objects.create_user("mana", password=CLAVE), MANAGER)
        self.assertEqual(self.titulos(), [
            "Administrar clientes y técnicos", "Administrar equipos", "Administrar proformas",
            "Administrar órdenes de trabajo", "Revisar información general",
        ])
        # Una sola sección con pestañas Clientes / Técnicos
        r = self.client.get(reverse("clientes:lista"))
        self.assertContains(r, reverse("trabajos:tecnicos"))
        self.assertEqual((r.context["n_clientes"], r.context["n_tecnicos"]), (1, 1))
        self.assertContains(self.client.get(reverse("trabajos:tecnicos")), "Luis")
        for m in self.client.get(reverse("inicio")).context["mosaicos"]:
            self.assertEqual(self.client.get(m["url"]).status_code, 200, m["url"])
        for url in [reverse("facturas:lista"), reverse("facturas:nueva"), reverse("dashboard"), reverse("finanzas"),
                    reverse("usuarios:lista")]:
            r = self.client.get(url)
            self.assertEqual((r.status_code, r.url), (302, reverse("inicio")), url)

    def test_menu_tecnico_y_sus_limites(self):
        entrar_como(self.client, self.tec, TECNICO)
        self.assertEqual(self.titulos(), ["Mis órdenes de trabajo", "Generar informe"])
        for url in [reverse("trabajos:proformas"), reverse("trabajos:orden_nueva"), reverse("trabajos:tecnicos"),
                    reverse("clientes:lista"), reverse("clientes:equipos"), reverse("facturas:lista"),
                    reverse("dashboard"), reverse("informacion")]:
            r = self.client.get(url)
            self.assertEqual((r.status_code, r.url), (302, reverse("inicio")), url)

    def test_informacion_general(self):
        entrar_como(self.client, User.objects.create_user("mana", password=CLAVE), MANAGER)
        atrasada = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Atrasada", fecha_fin=timezone.localdate() - timedelta(days=2))
        r = self.client.get(reverse("informacion"))
        self.assertEqual(r.context["kpis"]["atrasadas"], 1)
        self.assertEqual(r.context["kpis"]["sin_tecnico"], 1)
        self.assertContains(r, atrasada.numero)


class ClienteDatosFacturacionTests(Base):
    def setUp(self):
        super().setUp()
        entrar_como(self.client, User.objects.create_user("mana", password=CLAVE), MANAGER)

    def test_manager_crea_cliente_con_retencion_y_contacto(self):
        r = self.client.post(reverse("clientes:nuevo"), {
            "nombre": "Conjunto Las Lomas", "identificacion": "1790000002001", "agente_retencion": "on",
            "email": "admin@laslomas.test", "direccion": "Av. Siempre Viva 456", "telefono": "022222222",
            "telefono_contacto": "Sr. Pérez 0991234567", "dias_credito": 30, "activo": "on", "notas": "",
        })
        c = Cliente.objects.get(nombre="Conjunto Las Lomas")
        self.assertRedirects(r, c.get_absolute_url())
        self.assertTrue(c.agente_retencion)
        self.assertEqual(c.telefono_contacto, "Sr. Pérez 0991234567")
        self.assertEqual(c.faltan_para_facturar, [])
        r = self.client.get(c.get_absolute_url())
        self.assertContains(r, "Agente de retención")
        self.assertNotContains(r, "Faltan datos para facturar")

    def test_aviso_de_datos_incompletos(self):
        self.assertEqual(self.cliente.faltan_para_facturar, ["RUC/cédula", "email"])  # tiene dirección
        self.assertContains(self.client.get(self.cliente.get_absolute_url()), "Faltan datos para facturar")
        r = self.client.get(reverse("clientes:lista") + "?incompletos=1")
        self.assertEqual(list(r.context["pagina"]), [Cliente.objects.get(pk=self.cliente.pk)])

    def test_aviso_en_la_factura(self):
        entrar_como(self.client, User.objects.create_user("jefa", password=CLAVE), ADMINISTRADOR)
        r = self.client.get(reverse("facturas:nueva"))
        self.assertIn(str(self.cliente.pk), r.context["faltantes_clientes"])
