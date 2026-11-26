"""Varias empresas: registro, cuentas que quedan en la empresa de quien las crea y aislamiento de los datos."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse

from apps.clientes.models import Cliente, Equipo
from apps.configuracion.actual import empresa_actual, usar_empresa
from apps.configuracion.models import Empresa
from apps.facturas.models import Factura, Pago
from apps.trabajos.models import FormaPago, OrdenTrabajo, Proforma
from apps.usuarios.models import empresa_de, unir_a_empresa
from apps.usuarios.roles import ADMINISTRADOR, MANAGER, TECNICO, roles_de
from apps.usuarios.tests.utils import TestCase, entrar_como

CLAVE = "Clave-Segura-987"


def registrar(client, empresa="EmpresaAutos", usuario="duena", **extra):
    datos = {"empresa": empresa, "first_name": "Dueña", "last_name": "Autos", "username": usuario,
             "email": f"{usuario}@ejemplo.test", "password1": CLAVE, "password2": CLAVE}
    datos.update(extra)
    return client.post(reverse("registro"), datos)


class RegistroTests(TestCase):
    unir_cuentas_nuevas = False

    def test_registro_crea_empresa_y_administrador(self):
        r = registrar(self.client)
        self.assertRedirects(r, reverse("inicio"), fetch_redirect_response=False)
        duena = User.objects.get(username="duena")
        empresa = empresa_de(duena)
        self.assertEqual(empresa.nombre, "EmpresaAutos")
        self.assertEqual(roles_de(duena), [ADMINISTRADOR])
        self.assertFalse(duena.is_staff or duena.is_superuser)
        self.assertEqual(FormaPago._base_manager.filter(empresa=empresa).count(), 4)
        # Entra directamente con el rol Administrador y la barra muestra Novera + el nombre de la empresa
        r = self.client.get(reverse("inicio"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '<span class="marca-empresa">EmpresaAutos</span>')
        self.assertContains(r, "Usuarios y accesos")

    def test_validaciones(self):
        User.objects.create_user("ocupado", password=CLAVE)
        r = registrar(self.client, usuario="Ocupado")
        self.assertIn("username", r.context["form"].errors)
        r = registrar(self.client, empresa="   ", usuario="nueva")
        self.assertIn("empresa", r.context["form"].errors)
        r = registrar(self.client, usuario="nueva2", password2="otra-cosa")
        self.assertIn("password2", r.context["form"].errors)
        self.assertFalse(Empresa.objects.filter(nombre="EmpresaAutos").exists())

    def test_enlace_desde_el_login(self):
        self.assertContains(self.client.get(reverse("login")), reverse("registro"))

    @override_settings(NOVERA_REGISTRO_ABIERTO=False)
    def test_registro_cerrado(self):
        self.assertEqual(self.client.get(reverse("registro")).status_code, 404)
        self.assertEqual(registrar(self.client).status_code, 404)
        self.assertNotContains(self.client.get(reverse("login")), reverse("registro"))

    def test_con_sesion_iniciada_vuelve_al_inicio(self):
        registrar(self.client)
        self.assertRedirects(self.client.get(reverse("registro")), reverse("inicio"), fetch_redirect_response=False)


class CuentasDeLaEmpresaTests(TestCase):
    """El ejemplo del pedido: se registra, crea 1 manager y 2 técnicos, y todos quedan en su empresa."""

    unir_cuentas_nuevas = False

    def test_cuentas_creadas_quedan_en_la_empresa(self):
        registrar(self.client)
        duena = User.objects.get(username="duena")
        empresa = empresa_de(duena)
        for usuario, rol in [("gerente", MANAGER), ("tec1", TECNICO), ("tec2", TECNICO)]:
            r = self.client.post(reverse("usuarios:nueva"), {
                "first_name": usuario, "username": usuario, "roles": [rol], "password1": CLAVE, "password2": CLAVE,
            })
            self.assertRedirects(r, reverse("usuarios:lista"), fetch_redirect_response=False)
        for usuario in ("gerente", "tec1", "tec2"):
            self.assertEqual(empresa_de(User.objects.get(username=usuario)), empresa, usuario)

        # El Manager crea un técnico desde su menú: también queda en la empresa
        self.client.post(reverse("logout"))
        gerente = User.objects.get(username="gerente")
        entrar_como(self.client, gerente, MANAGER)
        self.client.post(reverse("trabajos:tecnico_nuevo"), {
            "first_name": "Tres", "username": "tec3", "password1": CLAVE, "password2": CLAVE,
        })
        self.assertEqual(empresa_de(User.objects.get(username="tec3")), empresa)

    def test_cuenta_sin_empresa_no_entra(self):
        suelta = User.objects.create_user("suelta", password=CLAVE)
        self.client.force_login(suelta)
        r = self.client.get(reverse("inicio"))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "no pertenece a ninguna empresa", status_code=403)


class AislamientoTests(TestCase):
    """Cada cuenta solo ve los datos de su empresa, aunque conozca el número (id) de los de otra."""

    unir_cuentas_nuevas = False

    def setUp(self):
        self.a = self.empresa
        self.b = Empresa.objects.create(nombre="Otra Empresa")
        FormaPago.crear_iniciales(self.b)
        self.datos = {}
        for empresa in (self.a, self.b):
            with usar_empresa(empresa):
                cliente = Cliente.objects.create(nombre="Edificio Central")  # mismo nombre en las dos: se permite
                equipo = Equipo.objects.create(cliente=cliente, nombre="Ascensor 1")
                factura = Factura.objects.create(
                    numero="001-001-000000001", cliente=cliente, periodo=date(2026, 1, 1), fecha_emision=date(2026, 1, 5),
                    subtotal=Decimal("100"), iva=Decimal("15"), total=Decimal("115"),
                )
                Pago.objects.create(factura=factura, monto=Decimal("10"))
                proforma = Proforma.objects.create(cliente=cliente, estado=Proforma.Estado.AUTORIZADA)
                orden = OrdenTrabajo.objects.create(cliente=cliente, titulo=f"Trabajo de {empresa}")
                admin = User.objects.create_user(f"admin-{empresa.pk}", password=CLAVE)
                tec = User.objects.create_user(f"tec-{empresa.pk}", password=CLAVE, first_name=f"Tec {empresa}")
                unir_a_empresa(admin, empresa)
                unir_a_empresa(tec, empresa)
                from apps.usuarios.roles import asignar_roles

                asignar_roles(tec, [TECNICO])
                orden.tecnicos.add(tec)
            self.datos[empresa.pk] = dict(cliente=cliente, equipo=equipo, factura=factura, proforma=proforma,
                                          orden=orden, admin=admin, tec=tec)
        self.de_a, self.de_b = self.datos[self.a.pk], self.datos[self.b.pk]

    def test_numeracion_independiente(self):
        self.assertEqual((self.de_a["proforma"].numero, self.de_b["proforma"].numero), ("PF-00001", "PF-00001"))
        self.assertEqual((self.de_a["orden"].numero, self.de_b["orden"].numero), ("OT-00001", "OT-00001"))

    def test_listados_solo_de_su_empresa(self):
        entrar_como(self.client, self.de_b["admin"], ADMINISTRADOR)
        r = self.client.get(reverse("clientes:lista"))
        self.assertContains(r, reverse("clientes:detalle", args=[self.de_b["cliente"].pk]))
        self.assertNotContains(r, reverse("clientes:detalle", args=[self.de_a["cliente"].pk]))
        r = self.client.get(reverse("trabajos:ordenes"))
        self.assertContains(r, "Trabajo de Otra Empresa")
        self.assertNotContains(r, "Trabajo de Empresa de pruebas")
        r = self.client.get(reverse("usuarios:lista"))
        self.assertContains(r, "admin-%d" % self.b.pk)
        self.assertNotContains(r, "admin-%d" % self.a.pk)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("facturas:lista")).status_code, 200)
        self.assertEqual(self.client.get(reverse("informacion")).status_code, 200)

    def test_no_se_abren_datos_de_otra_empresa(self):
        entrar_como(self.client, self.de_b["admin"], ADMINISTRADOR)
        ajenos = [
            reverse("clientes:detalle", args=[self.de_a["cliente"].pk]),
            reverse("clientes:editar", args=[self.de_a["cliente"].pk]),
            reverse("clientes:equipo", args=[self.de_a["equipo"].pk]),
            reverse("facturas:detalle", args=[self.de_a["factura"].pk]),
            reverse("facturas:editar", args=[self.de_a["factura"].pk]),
            reverse("trabajos:proforma", args=[self.de_a["proforma"].pk]),
            reverse("trabajos:proforma_pdf", args=[self.de_a["proforma"].pk]),
            reverse("trabajos:orden", args=[self.de_a["orden"].pk]),
            reverse("trabajos:orden_editar", args=[self.de_a["orden"].pk]),
            reverse("usuarios:editar", args=[self.de_a["admin"].pk]),
        ]
        for url in ajenos:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        # Ni tampoco se modifican por POST
        r = self.client.post(reverse("usuarios:activar", args=[self.de_a["admin"].pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(User.objects.get(pk=self.de_a["admin"].pk).is_active)
        r = self.client.post(reverse("facturas:anular", args=[self.de_a["factura"].pk]), {"motivo": "x"})
        self.assertEqual(r.status_code, 404)
        # Con su propia factura sí funciona
        self.assertEqual(self.client.get(reverse("facturas:detalle", args=[self.de_b["factura"].pk])).status_code, 200)

    def test_manager_solo_ve_y_edita_sus_tecnicos(self):
        manager = User.objects.create_user("man-b", password=CLAVE)
        unir_a_empresa(manager, self.b)
        entrar_como(self.client, manager, MANAGER)
        r = self.client.get(reverse("trabajos:tecnicos"))
        self.assertContains(r, "Tec Otra Empresa")
        self.assertNotContains(r, "Tec Empresa de pruebas")
        self.assertEqual(self.client.get(reverse("trabajos:tecnico_editar", args=[self.de_a["tec"].pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("trabajos:tecnico_habilitar", args=[self.de_a["tec"].pk])).status_code, 404)
        # En el formulario de orden solo se ofrecen sus técnicos, clientes y equipos
        form = self.client.get(reverse("trabajos:orden_nueva")).context["form"]
        self.assertEqual(list(form.fields["tecnicos"].queryset), [self.de_b["tec"]])
        self.assertEqual(list(form.fields["cliente"].queryset), [self.de_b["cliente"]])
        self.assertEqual(list(form.fields["equipos"].queryset), [self.de_b["equipo"]])

    def test_tecnico_solo_ve_sus_ordenes(self):
        entrar_como(self.client, self.de_b["tec"], TECNICO)
        r = self.client.get(reverse("trabajos:ordenes"))
        self.assertContains(r, "Trabajo de Otra Empresa")
        self.assertNotContains(r, "Trabajo de Empresa de pruebas")
        self.assertEqual(self.client.get(reverse("trabajos:orden", args=[self.de_a["orden"].pk])).status_code, 404)

    def test_filtros_de_formularios_por_empresa(self):
        from apps.facturas.dashboard import FiltroPanelForm
        from apps.facturas.forms import FiltroFacturasForm

        with usar_empresa(self.b):
            self.assertEqual(list(FiltroFacturasForm().fields["cliente"].queryset), [self.de_b["cliente"]])
            self.assertEqual(list(FiltroPanelForm().fields["cliente"].queryset), [self.de_b["cliente"]])

    def test_mismo_numero_de_factura_en_otra_empresa_no_es_duplicado(self):
        with usar_empresa(self.b):
            self.assertEqual(Factura.objects.buscar_duplicado("001-001-000000001"), self.de_b["factura"])
            self.assertEqual(Factura.objects.count(), 1)
            self.assertEqual(Pago.objects.count(), 1)

    def test_la_empresa_activa_se_restaura_tras_cada_peticion(self):
        entrar_como(self.client, self.de_b["admin"], ADMINISTRADOR)
        self.client.get(reverse("inicio"))
        self.assertEqual(empresa_actual(), self.a)  # la de la prueba, no la de la cuenta que hizo la petición

    def test_logo_y_nombre_de_su_empresa(self):
        Empresa.objects.filter(pk=self.b.pk).update(nombre="")
        entrar_como(self.client, self.de_b["admin"], ADMINISTRADOR)
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, '<span class="marca-empresa">Empresa</span>')
        self.assertNotContains(r, 'class="marca-logo"')
        self.assertEqual(self.client.get(reverse("configuracion:logo")).status_code, 404)
