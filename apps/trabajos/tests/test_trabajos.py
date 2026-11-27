from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from apps.usuarios.tests.utils import TestCase
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
        datos = {"cliente": self.cliente.pk, "fecha": timezone.localdate().isoformat(), "validez_dias": 15,
                 "porcentaje_iva": "15", "descripcion": "", "notas": "", "forma_pago": "50% Anticipo 50% Al terminar"}
        datos.update(lineas(
            {"tipo": "SERVICIO", "descripcion": "Cambio de cables del ascensor", "cantidad": "8", "unidad": "h", "precio_unitario": "25"},
            {"tipo": "MATERIAL", "descripcion": "Cable de acero 10 mm", "cantidad": "30", "unidad": "m", "precio_unitario": "4.5"},
        ))
        r = self.client.post(reverse("trabajos:proforma_nueva"), datos)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return Proforma.objects.get()

    def autorizar_como_manager(self, p, accion="autorizar", observacion=""):
        entrar_como(self.client, User.objects.get_or_create(username="mana")[0], MANAGER)
        r = self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": accion, "observacion": observacion})
        entrar_como(self.client, self.admin, ADMINISTRADOR)
        return r

    def test_solicitar_autorizacion_y_aprobacion_genera_orden(self):
        p = self.crear_proforma()
        self.assertEqual((p.numero, p.subtotal, p.total, p.estado), ("PF-00001", Decimal("335.00"), Decimal("385.25"), "POR_AUTORIZAR"))
        self.assertEqual(p.titulo, "Cambio de cables del ascensor y 1 ítem más")  # resumen tomado del detalle
        # Sin autorizar no se puede enviar ni generar la orden
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "enviar"})
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "generar_orden"})
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "autorizar"})  # el admin no autoriza
        p.refresh_from_db()
        self.assertEqual(p.estado, "POR_AUTORIZAR")
        self.assertFalse(OrdenTrabajo.objects.exists())
        self.autorizar_como_manager(p)
        p.refresh_from_db()
        self.assertEqual((p.estado, p.autorizada_por.username), ("AUTORIZADA", "mana"))
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "enviar"})
        # Solo el Manager procesa; sin procesar no se genera la orden
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "procesar"})
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "generar_orden"})
        p.refresh_from_db()
        self.assertEqual(p.estado, "ENVIADA")
        self.assertFalse(OrdenTrabajo.objects.exists())
        self.autorizar_como_manager(p, "procesar")
        p.refresh_from_db()
        self.assertEqual((p.estado, p.procesada_por.username), ("PROCESADA", "mana"))
        # Aparece en «Nueva orden de trabajo» y se genera desde ahí (o desde la proforma)
        self.assertEqual(list(self.client.get(reverse("trabajos:orden_nueva")).context["proformas_listas"]), [p])
        r = self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "generar_orden"})
        orden = OrdenTrabajo.objects.get()
        self.assertRedirects(r, reverse("trabajos:orden_editar", args=[orden.pk]))
        p.refresh_from_db()
        self.assertEqual(p.estado, "APROBADA")
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "generar_orden"})
        self.assertEqual(OrdenTrabajo.objects.count(), 1)  # no se duplica
        self.assertEqual(list(self.client.get(reverse("trabajos:orden_nueva")).context["proformas_listas"]), [])
        self.assertEqual((orden.numero, orden.proforma, orden.ubicacion), ("OT-00001", p, "Av. Siempre Viva 123"))
        self.assertEqual(list(orden.recursos.values_list("descripcion", flat=True)), ["Cable de acero 10 mm"])

    def test_devolver_y_corregir(self):
        p = self.crear_proforma()
        r = self.autorizar_como_manager(p, "devolver")  # sin observación no se devuelve
        p.refresh_from_db()
        self.assertEqual(p.estado, "POR_AUTORIZAR")
        self.autorizar_como_manager(p, "devolver", "Revisar el precio de la mano de obra")
        p.refresh_from_db()
        self.assertEqual((p.estado, p.observacion_autorizacion), ("DEVUELTA", "Revisar el precio de la mano de obra"))
        self.assertContains(self.client.get(p.get_absolute_url()), "Revisar el precio de la mano de obra")
        # Al corregir y guardar vuelve a pedir autorización
        datos = {"cliente": self.cliente.pk, "fecha": timezone.localdate().isoformat(), "validez_dias": 15, "porcentaje_iva": "15"}
        l = p.lineas.order_by("pk")
        datos.update(lineas(*[{"id": x.pk, "proforma": p.pk, "tipo": x.tipo, "descripcion": x.descripcion, "cantidad": "8",
                                "unidad": x.unidad, "precio_unitario": "20"} for x in l], iniciales=l.count()))
        self.client.post(reverse("trabajos:proforma_editar", args=[p.pk]), datos)
        p.refresh_from_db()
        self.assertEqual(p.estado, "POR_AUTORIZAR")

    def test_autorizada_no_se_edita_salvo_que_el_manager_la_devuelva(self):
        p = self.crear_proforma()
        self.autorizar_como_manager(p)
        r = self.client.get(reverse("trabajos:proforma_editar", args=[p.pk]))
        self.assertRedirects(r, p.get_absolute_url())
        self.assertNotContains(self.client.get(p.get_absolute_url()), reverse("trabajos:proforma_editar", args=[p.pk]))
        self.autorizar_como_manager(p, "devolver", "Cambiar la garantía")
        p.refresh_from_db()
        self.assertEqual(p.estado, "DEVUELTA")
        self.assertEqual(self.client.get(reverse("trabajos:proforma_editar", args=[p.pk])).status_code, 200)

    def test_manager_crea_y_queda_autorizada(self):
        entrar_como(self.client, User.objects.create_user("mana2", password=CLAVE), MANAGER)
        p = self.crear_proforma()
        self.assertEqual((p.estado, p.autorizada_por.username), ("AUTORIZADA", "mana2"))
        r = self.client.get(reverse("trabajos:proformas"))
        self.assertContains(r, "Por autorizar")

    def test_ordenar_listado_y_nueva_desde_el_detalle(self):
        p1 = self.crear_proforma()
        p2 = Proforma.objects.create(cliente=self.cliente, fecha=p1.fecha - timedelta(days=3), empresa=p1.empresa)
        p3 = Proforma.objects.create(cliente=self.cliente, fecha=p1.fecha - timedelta(days=1), empresa=p1.empresa)
        url = reverse("trabajos:proformas")
        numeros = lambda orden: [p.numero for p in self.client.get(url, {"orden": orden}).context["pagina"]]
        self.assertEqual(numeros(""), ["PF-00003", "PF-00002", "PF-00001"])  # por defecto, número descendente
        self.assertEqual(numeros("numero"), ["PF-00001", "PF-00002", "PF-00003"])
        self.assertEqual(numeros("-fecha"), [p1.numero, p3.numero, p2.numero])
        self.assertEqual(numeros("fecha"), [p2.numero, p3.numero, p1.numero])
        self.assertEqual(numeros("no-existe"), ["PF-00003", "PF-00002", "PF-00001"])
        self.assertContains(self.client.get(url, {"orden": "numero"}), '<option value="numero" selected>')
        self.assertContains(self.client.get(p1.get_absolute_url()), f'href="{reverse("trabajos:proforma_nueva")}"')

    def test_formas_de_pago(self):
        from apps.trabajos.models import FormaPago

        self.assertEqual(list(FormaPago.objects.filter(activa=True).values_list("nombre", flat=True)), [
            "100% Contra entrega", "70% Anticipo 30% Al terminar", "50% Anticipo 50% Al terminar", "40% Anticipo 60% Al terminar",
        ])
        r = self.client.post(reverse("trabajos:forma_pago_rapida"), {"nombre": "60% Anticipo 40% Al terminar"})
        self.assertEqual(r.json()["nombre"], "60% Anticipo 40% Al terminar")
        self.assertEqual(self.client.post(reverse("trabajos:forma_pago_rapida"), {"nombre": "60% anticipo 40% al terminar"}).status_code, 400)
        fp = FormaPago.objects.get(nombre="100% Contra entrega")
        self.client.post(reverse("trabajos:forma_pago_activar", args=[fp.pk]))
        opciones = [v for v, _ in self.client.get(reverse("trabajos:proforma_nueva")).context["form"].fields["forma_pago"].choices]
        self.assertNotIn("100% Contra entrega", opciones)
        self.assertIn("60% Anticipo 40% Al terminar", opciones)

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

    def test_editar_orden_existente_con_tecnicos_y_equipos(self):
        equipo = Equipo.objects.create(cliente=self.cliente, nombre="Ascensor 1")
        o = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Revisión")
        o.tecnicos.add(self.tec)
        o.equipos.add(equipo)
        # Aunque el técnico y el equipo ya no estén activos, la orden se sigue pudiendo editar
        self.tec.is_active = False
        self.tec.save()
        equipo.activo = False
        equipo.save()
        r = self.client.get(reverse("trabajos:orden_editar", args=[o.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.tec, r.context["form"].fields["tecnicos"].queryset)
        self.assertIn(equipo, r.context["form"].fields["equipos"].queryset)
        r = self.client.post(reverse("trabajos:orden_editar", args=[o.pk]),
                             datos_orden(self.cliente, titulo="Revisión anual", tecnicos=[self.tec.pk], equipos=[equipo.pk]))
        self.assertRedirects(r, o.get_absolute_url())
        o.refresh_from_db()
        self.assertEqual((o.titulo, list(o.tecnicos.all())), ("Revisión anual", [self.tec]))

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

    def test_editar_factura_con_orden_cancelada(self):
        o = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Uno")
        hoy = timezone.localdate()
        f = Factura.objects.create(numero="REC-00009", tipo="RECIBO", cliente=self.cliente, periodo=hoy, fecha_emision=hoy,
                                   subtotal=10, total=10)
        f.ordenes.add(o)
        o.estado = OrdenTrabajo.Estado.CANCELADA
        o.save()
        r = self.client.get(reverse("facturas:editar", args=[f.pk]))
        self.assertIn(o, r.context["form"].fields["ordenes"].queryset)

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

    def test_manager_crea_tecnico_con_su_perfil(self):
        r = self.client.post(reverse("trabajos:tecnico_nuevo"), {
            "first_name": "Ana", "last_name": "Ruiz", "username": "ana", "grado_academico": "Tecnóloga",
            "capacidades": "Certificación Otis", "telefono": "0990000001", "direccion": "Quito norte",
            "password1": "Clave-Segura-987", "password2": "Clave-Segura-987",
        })
        self.assertRedirects(r, reverse("trabajos:tecnicos"))
        ana = User.objects.get(username="ana")
        self.assertEqual(roles_de(ana), [TECNICO])
        self.assertEqual((ana.perfil_tecnico.grado_academico, ana.perfil_tecnico.telefono), ("Tecnóloga", "0990000001"))
        self.assertTrue(ana.check_password("Clave-Segura-987"))
        # Editar el perfil sin tocar la clave
        r = self.client.post(reverse("trabajos:tecnico_editar", args=[ana.pk]), {
            "first_name": "Ana", "last_name": "Ruiz", "username": "ana", "grado_academico": "Ingeniera",
            "capacidades": "", "telefono": "0990000002", "direccion": "", "activo": "on",
        })
        ana.refresh_from_db()
        self.assertEqual(ana.perfil_tecnico.grado_academico, "Ingeniera")
        self.assertTrue(ana.check_password("Clave-Segura-987"))
        self.assertContains(self.client.get(reverse("trabajos:tecnicos")), "Ingeniera")

    def test_habilitar_y_deshabilitar(self):
        self.client.post(reverse("trabajos:tecnico_habilitar", args=[self.tec.pk]))
        self.tec.refresh_from_db()
        self.assertFalse(self.tec.is_active)
        self.assertEqual(self.client_class().post(reverse("login"), {"username": "luis", "password": CLAVE}).status_code, 200)
        self.client.post(reverse("trabajos:tecnico_habilitar", args=[self.tec.pk]))
        self.tec.refresh_from_db()
        self.assertTrue(self.tec.is_active)

    def test_solo_el_manager_ve_los_datos_de_los_tecnicos(self):
        entrar_como(self.client, User.objects.create_user("jefa", password=CLAVE), ADMINISTRADOR)
        for url in [reverse("trabajos:tecnicos"), reverse("trabajos:tecnico_nuevo"),
                    reverse("trabajos:tecnico_editar", args=[self.tec.pk])]:
            self.assertRedirects(self.client.get(url), reverse("inicio"), fetch_redirect_response=False)
        self.assertNotContains(self.client.get(reverse("clientes:lista")), reverse("trabajos:tecnicos"))

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


class ProformaPdfTests(Base):
    def setUp(self):
        super().setUp()
        self.p = Proforma.objects.create(
            cliente=self.cliente, titulo="Cambio de cables", forma_pago="100% Contra entrega", garantia_cantidad=3,
            garantia_nota="Cubre repuestos", condiciones_generales="1. Precios incluyen IVA.",
        )
        self.p.lineas.create(descripcion="Mano de obra", cantidad=8, unidad="h", precio_unitario=25)
        self.p.estado = Proforma.Estado.AUTORIZADA
        self.p.save()

    def test_garantia_en_texto(self):
        self.assertEqual(self.p.garantia, "3 meses")
        self.p.garantia_cantidad = 1
        self.p.garantia_unidad = "ANIOS"
        self.assertEqual(self.p.garantia, "1 año")

    def test_descargar_pdf_carta(self):
        entrar_como(self.client, User.objects.create_user("jefa", password=CLAVE), ADMINISTRADOR)
        r = self.client.get(reverse("trabajos:proforma_pdf", args=[self.p.pk]))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("PF-00001", r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"%PDF"))
        # Tamaño carta: 8,5 × 11 pulgadas = 612 × 792 puntos
        from django.template.loader import render_to_string
        from weasyprint import HTML

        from apps.configuracion.models import datos_emisor, tema_proforma

        html = render_to_string("trabajos/proforma_pdf.html", {"p": self.p, "lineas": self.p.lineas.all(),
                                                                 "empresa": datos_emisor(), "tema": tema_proforma()})
        pagina = HTML(string=html).render().pages[0]
        self.assertEqual((round(pagina.width * 0.75), round(pagina.height * 0.75)), (612, 792))
        r = self.client.get(reverse("trabajos:proforma_pdf", args=[self.p.pk]) + "?ver=1")
        self.assertIn("inline", r["Content-Disposition"])

    def test_sin_autorizar_no_hay_pdf(self):
        entrar_como(self.client, User.objects.create_user("jefa", password=CLAVE), ADMINISTRADOR)
        self.p.estado = Proforma.Estado.POR_AUTORIZAR
        self.p.save()
        r = self.client.get(reverse("trabajos:proforma_pdf", args=[self.p.pk]))
        self.assertRedirects(r, self.p.get_absolute_url())
        r = self.client.get(self.p.get_absolute_url())
        self.assertNotContains(r, reverse("trabajos:proforma_pdf", args=[self.p.pk]))
        self.p.estado = Proforma.Estado.AUTORIZADA
        self.p.save()
        self.assertContains(self.client.get(self.p.get_absolute_url()), "Descargar PDF")

    def test_tecnico_no_descarga_proformas(self):
        entrar_como(self.client, self.tec, TECNICO)
        r = self.client.get(reverse("trabajos:proforma_pdf", args=[self.p.pk]))
        self.assertEqual(r.status_code, 302)

    def test_nueva_proforma_propone_condiciones_de_la_ultima(self):
        entrar_como(self.client, User.objects.create_user("mana", password=CLAVE), MANAGER)
        form = self.client.get(reverse("trabajos:proforma_nueva")).context["form"]
        self.assertEqual(form.initial["forma_pago"], "100% Contra entrega")
        self.assertEqual(form.initial["condiciones_generales"], "1. Precios incluyen IVA.")
        self.assertEqual(form.initial["garantia_cantidad"], 3)
