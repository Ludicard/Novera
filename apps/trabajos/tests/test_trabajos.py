from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.trabajos.models import OrdenTrabajo, Proforma, Recurso, Tarea
from apps.usuarios.roles import ADMINISTRADOR, MANAGER, TECNICO, asignar_roles
from apps.usuarios.tests.utils import entrar_como

CLAVE = "clave-segura-123"


def lineas(*filas, prefijo="lineas", iniciales=0):
    datos = {f"{prefijo}-TOTAL_FORMS": str(len(filas)), f"{prefijo}-INITIAL_FORMS": str(iniciales),
             f"{prefijo}-MIN_NUM_FORMS": "0", f"{prefijo}-MAX_NUM_FORMS": "1000"}
    for i, f in enumerate(filas):
        for k, v in f.items():
            datos[f"{prefijo}-{i}-{k}"] = v
    return datos


class FlujoProformaOrdenTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("jefa", password=CLAVE, first_name="Jefa")
        entrar_como(self.client, self.admin, ADMINISTRADOR)
        self.cliente = Cliente.objects.create(nombre="Edificio Central", direccion="Av. Siempre Viva 123")
        self.tec = User.objects.create_user("luis", password=CLAVE, first_name="Luis")
        asignar_roles(self.tec, [TECNICO])

    def crear_proforma(self):
        datos = {"cliente": self.cliente.pk, "titulo": "Cambio de cables del ascensor", "fecha": timezone.localdate().isoformat(),
                 "validez_dias": 15, "porcentaje_iva": "15", "descripcion": "", "notas": ""}
        datos.update(lineas(
            {"tipo": "SERVICIO", "descripcion": "Mano de obra", "cantidad": "8", "unidad": "h", "precio_unitario": "25"},
            {"tipo": "MATERIAL", "descripcion": "Cable de acero 10 mm", "cantidad": "30", "unidad": "m", "precio_unitario": "4.5"},
        ))
        r = self.client.post(reverse("trabajos:proforma_nueva"), datos)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return Proforma.objects.get()

    def test_proforma_numeracion_y_totales(self):
        p = self.crear_proforma()
        self.assertEqual(p.numero, "PF-00001")
        self.assertEqual(p.subtotal, Decimal("335.00"))
        self.assertEqual(p.total, Decimal("385.25"))
        self.assertEqual(self.client.get(p.get_absolute_url()).status_code, 200)

    def test_proforma_sin_lineas_no_se_guarda(self):
        datos = {"cliente": self.cliente.pk, "titulo": "X", "fecha": timezone.localdate().isoformat(), "validez_dias": 15,
                 "porcentaje_iva": "15"}
        datos.update(lineas())
        r = self.client.post(reverse("trabajos:proforma_nueva"), datos)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Proforma.objects.exists())

    def test_aprobar_genera_la_orden_con_materiales(self):
        p = self.crear_proforma()
        r = self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "aprobar"})
        orden = OrdenTrabajo.objects.get()
        self.assertRedirects(r, reverse("trabajos:orden_editar", args=[orden.pk]))
        self.assertEqual((orden.numero, orden.cliente, orden.proforma, orden.ubicacion),
                         ("OT-00001", self.cliente, p, "Av. Siempre Viva 123"))
        self.assertEqual(list(orden.recursos.values_list("tipo", "descripcion")), [("MATERIAL", "Cable de acero 10 mm")])
        p.refresh_from_db()
        self.assertEqual(p.estado, "APROBADA")
        # Ya no se puede aprobar otra vez ni editar
        self.client.post(reverse("trabajos:proforma_estado", args=[p.pk]), {"accion": "aprobar"})
        self.assertEqual(OrdenTrabajo.objects.count(), 1)
        self.assertRedirects(self.client.get(reverse("trabajos:proforma_editar", args=[p.pk])), p.get_absolute_url())

    def test_editar_orden_con_herramientas_fechas_y_horas(self):
        orden = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Mantenimiento")
        datos = {"cliente": self.cliente.pk, "titulo": "Mantenimiento", "ubicacion": "", "horas_estimadas": "12",
                 "fecha_inicio": "2026-12-01", "fecha_fin": "2026-12-03", "descripcion": "", "notas": ""}
        datos.update(lineas({"tipo": "HERRAMIENTA", "descripcion": "Taladro", "cantidad": "1", "unidad": "u"}, prefijo="recursos"))
        r = self.client.post(reverse("trabajos:orden_editar", args=[orden.pk]), datos)
        self.assertRedirects(r, orden.get_absolute_url())
        orden.refresh_from_db()
        self.assertEqual((orden.horas_estimadas, str(orden.fecha_fin)), (Decimal("12.0"), "2026-12-03"))
        self.assertEqual(orden.recursos.get().tipo, Recurso.Tipo.HERRAMIENTA)

    def test_fin_antes_del_inicio(self):
        datos = {"cliente": self.cliente.pk, "titulo": "X", "fecha_inicio": "2026-12-05", "fecha_fin": "2026-12-01"}
        datos.update(lineas(prefijo="recursos"))
        r = self.client.post(reverse("trabajos:orden_nueva"), datos)
        self.assertContains(r, "no puede ser anterior al inicio")

    def test_asignar_tecnico_y_su_avance(self):
        orden = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Revisión", fecha_inicio=timezone.localdate())
        r = self.client.post(reverse("trabajos:asignar"), {
            "orden": orden.pk, "tecnico": self.tec.pk, "responsabilidades": "Revisar frenos y reportar",
            "fecha_limite": "", "horas_estimadas": "3",
        })
        self.assertRedirects(r, reverse("trabajos:asignar"))
        tarea = Tarea.objects.get()
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenTrabajo.Estado.EN_CURSO)  # ya empezó y tiene técnico
        # El técnico la ve y la marca como hecha
        entrar_como(self.client, self.tec, TECNICO)
        r = self.client.get(reverse("trabajos:mis_tareas"))
        self.assertContains(r, "Revisar frenos y reportar")
        self.client.post(reverse("trabajos:tarea_avance", args=[tarea.pk]), {f"t{tarea.pk}-estado": "HECHA", f"t{tarea.pk}-comentario": "Listo"})
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, "HECHA")
        self.assertIsNotNone(tarea.completada)

    def test_solo_tecnicos_en_el_selector(self):
        manager = User.objects.create_user("mana", password=CLAVE)
        asignar_roles(manager, [MANAGER])
        r = self.client.get(reverse("trabajos:asignar"))
        tecnicos = list(r.context["form"].fields["tecnico"].queryset)
        self.assertEqual(tecnicos, [self.tec])

    def test_ordenes_sin_tecnico(self):
        OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Sin nadie")
        r = self.client.get(reverse("trabajos:ordenes") + "?estado=sin_tecnico")
        self.assertEqual(r.context["pagina"].paginator.count, 1)


class PermisosPorRolTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Torre Sur")
        self.tec = User.objects.create_user("luis", password=CLAVE)
        self.otro = User.objects.create_user("ana", password=CLAVE)
        asignar_roles(self.otro, [TECNICO])
        self.mia = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Mía")
        self.ajena = OrdenTrabajo.objects.create(cliente=self.cliente, titulo="Ajena")
        Tarea.objects.create(orden=self.mia, tecnico=self.tec, responsabilidades="Hacer X")
        Tarea.objects.create(orden=self.ajena, tecnico=self.otro, responsabilidades="Hacer Y")
        entrar_como(self.client, self.tec, TECNICO)

    def test_tecnico_ve_solo_sus_ordenes(self):
        r = self.client.get(reverse("trabajos:ordenes"))
        self.assertEqual([o.titulo for o in r.context["pagina"]], ["Mía"])
        self.assertEqual(self.client.get(self.mia.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.ajena.get_absolute_url()).status_code, 404)

    def test_tecnico_no_entra_a_gestion_ni_finanzas(self):
        for url in [reverse("trabajos:proformas"), reverse("trabajos:asignar"), reverse("trabajos:orden_nueva"),
                    reverse("facturas:lista"), reverse("clientes:lista"), reverse("dashboard"), reverse("finanzas"),
                    reverse("trabajos:orden_editar", args=[self.mia.pk])]:
            r = self.client.get(url)
            self.assertEqual((r.status_code, r.url), (302, reverse("inicio")), url)

    def test_tecnico_no_actualiza_tareas_ajenas(self):
        ajena = Tarea.objects.get(orden=self.ajena)
        r = self.client.post(reverse("trabajos:tarea_avance", args=[ajena.pk]), {f"t{ajena.pk}-estado": "HECHA"})
        self.assertEqual(r.status_code, 404)

    def test_menu_de_inicio_por_rol(self):
        r = self.client.get(reverse("inicio"))
        self.assertEqual([m["titulo"] for m in r.context["mosaicos"]], ["Mis tareas", "Mis órdenes de trabajo"])
        jefa = User.objects.create_user("jefa", password=CLAVE)
        entrar_como(self.client, jefa, ADMINISTRADOR)
        r = self.client.get(reverse("inicio"))
        self.assertEqual([m["titulo"] for m in r.context["mosaicos"]], [
            "Administrar proformas", "Órdenes de trabajo", "Asignar tareas", "Cargar datos financieros",
            "Revisar información general",
        ])
        for m in r.context["mosaicos"]:
            self.assertEqual(self.client.get(m["url"]).status_code, 200, m["url"])
        # El Administrador sigue pudiendo entrar a clientes (solo cambia el menú)
        self.assertEqual(self.client.get(reverse("clientes:lista")).status_code, 200)
        # El Manager (gerente) es quien tiene «Administrar clientes» en su menú
        mana = User.objects.create_user("mana", password=CLAVE)
        entrar_como(self.client, mana, MANAGER)
        r = self.client.get(reverse("inicio"))
        self.assertEqual(r.context["mosaicos"][0]["titulo"], "Administrar clientes")
        self.assertNotIn("Administrar proformas", [m["titulo"] for m in r.context["mosaicos"]])

    def test_aviso_de_proformas_por_responder(self):
        jefa = User.objects.create_user("jefa", password=CLAVE)
        entrar_como(self.client, jefa, ADMINISTRADOR)
        Proforma.objects.create(cliente=self.cliente, titulo="Cotización pendiente")
        r = self.client.get(reverse("inicio"))
        self.assertEqual(r.context["mosaicos"][0]["alerta"], "1 por responder")

    def test_manager_gestiona_ordenes_pero_no_usuarios(self):
        mana = User.objects.create_user("mana", password=CLAVE)
        entrar_como(self.client, mana, MANAGER)
        self.assertEqual(self.client.get(reverse("trabajos:asignar")).status_code, 200)
        self.assertEqual(self.client.get(reverse("trabajos:proforma_nueva")).status_code, 200)
        self.assertEqual(self.client.get(reverse("usuarios:lista")).status_code, 302)

    def test_vencida_fin(self):
        self.mia.fecha_fin = timezone.localdate() - timedelta(days=1)
        self.assertTrue(self.mia.atrasada)
