from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.usuarios.roles import (
    ADMINISTRADOR, MANAGER, ROLES, SESION_ROL, TECNICO, agregar_rol, asignar_roles, quitar_rol, roles_de,
    roles_disponibles,
)
from apps.usuarios.tests.utils import entrar_como

CLAVE = "clave-segura-123"


class RolesTests(TestCase):
    def test_los_tres_roles_existen(self):
        self.assertTrue({"Administrador", "Manager", "Técnico"} <= set(Group.objects.values_list("name", flat=True)))

    def test_superusuario_sin_rol_pasa_a_administrador(self):
        admin = User.objects.create_superuser("jefe", "j@x.test", CLAVE)
        self.assertEqual(roles_de(admin), [ADMINISTRADOR])

    def test_varios_roles(self):
        u = User.objects.create_user("ana", password=CLAVE)
        asignar_roles(u, [TECNICO, MANAGER])
        self.assertEqual(roles_de(u), [MANAGER, TECNICO])
        quitar_rol(u, MANAGER)
        agregar_rol(u, MANAGER)
        agregar_rol(u, MANAGER)
        self.assertEqual(roles_de(u), [MANAGER, TECNICO])

    def test_administrador_puede_usar_los_tres(self):
        self.assertEqual(roles_disponibles([ADMINISTRADOR]), [MANAGER, ADMINISTRADOR, TECNICO])
        self.assertEqual(roles_disponibles([TECNICO]), [TECNICO])


class SeleccionDeRolTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("ana", password=CLAVE)
        self.elegir = reverse("usuarios:elegir_rol")

    def iniciar_sesion(self, siguiente=""):
        url = reverse("login") + (f"?next={siguiente}" if siguiente else "")
        return self.client.post(url, {"username": "ana", "password": CLAVE, "next": siguiente}, follow=True)

    def test_al_iniciar_sesion_sale_la_pantalla_aunque_tenga_un_solo_rol(self):
        asignar_roles(self.u, [TECNICO])
        r = self.iniciar_sesion()
        self.assertEqual(r.request["PATH_INFO"], self.elegir)
        opciones = [o["clave"] for o in r.context["opciones"]]
        self.assertEqual(opciones, [TECNICO])
        self.assertContains(r, "Selecciona tu rol")

    def test_solo_muestra_los_roles_con_acceso(self):
        asignar_roles(self.u, [MANAGER, TECNICO])
        r = self.iniciar_sesion()
        self.assertEqual([o["clave"] for o in r.context["opciones"]], [MANAGER, TECNICO])
        asignar_roles(self.u, [ADMINISTRADOR])
        r = self.client.get(self.elegir)
        self.assertEqual([o["clave"] for o in r.context["opciones"]], [MANAGER, ADMINISTRADOR, TECNICO])

    def test_sin_elegir_no_entra_a_la_app(self):
        asignar_roles(self.u, [MANAGER])
        self.client.force_login(self.u)
        r = self.client.get(reverse("facturas:lista") + "?estado=VENCIDA")
        self.assertRedirects(r, self.elegir + "?siguiente=%2Ffacturas%2F%3Festado%3DVENCIDA")

    def test_elegir_y_seguir_a_donde_iba(self):
        asignar_roles(self.u, [MANAGER, TECNICO])
        self.iniciar_sesion(siguiente="/facturas/")
        r = self.client.post(self.elegir, {"rol": TECNICO, "siguiente": "/facturas/"})
        self.assertRedirects(r, "/facturas/")
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.context["rol"], TECNICO)
        self.assertContains(r, "<b>Técnico</b>")

    def test_no_puede_elegir_un_rol_sin_acceso(self):
        asignar_roles(self.u, [TECNICO])
        self.client.force_login(self.u)
        r = self.client.post(self.elegir, {"rol": ADMINISTRADOR})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(SESION_ROL, self.client.session)
        r = self.client.post(self.elegir, {"rol": "inventado"})
        self.assertEqual(r.status_code, 400)

    def test_cada_inicio_de_sesion_vuelve_a_preguntar(self):
        asignar_roles(self.u, [MANAGER])
        self.iniciar_sesion()
        self.client.post(self.elegir, {"rol": MANAGER})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.client.post(reverse("logout"))
        r = self.iniciar_sesion()
        self.assertEqual(r.request["PATH_INFO"], self.elegir)

    def test_cambiar_de_rol_desde_la_barra(self):
        entrar_como(self.client, self.u, MANAGER, roles=[MANAGER, TECNICO])
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, f'href="{self.elegir}"')
        self.client.post(self.elegir, {"rol": TECNICO})
        self.assertEqual(self.client.get(reverse("dashboard")).context["rol"], TECNICO)

    def test_si_le_quitan_el_rol_activo_vuelve_a_elegir(self):
        entrar_como(self.client, self.u, MANAGER, roles=[MANAGER, TECNICO])
        quitar_rol(self.u, MANAGER)
        self.assertRedirects(self.client.get(reverse("dashboard")), self.elegir)

    def test_no_redirige_fuera_del_sitio(self):
        asignar_roles(self.u, [MANAGER])
        self.client.force_login(self.u)
        r = self.client.post(self.elegir, {"rol": MANAGER, "siguiente": "https://malicioso.test/"})
        self.assertEqual(r.url, reverse("dashboard"))

    def test_cuenta_sin_rol(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "aún no tiene un rol", status_code=403)
        self.assertEqual(self.client.get(self.elegir).status_code, 403)
        self.assertEqual(self.client.get("/salud/").status_code, 200)


class AdminRolesTests(TestCase):
    def test_admin_crea_usuario_con_varios_roles(self):
        jefe = User.objects.create_superuser("jefe", "j@x.test", CLAVE)
        entrar_como(self.client, jefe, ADMINISTRADOR)
        r = self.client.post(reverse("admin:auth_user_add"), {
            "username": "tec1", "roles": [MANAGER, TECNICO],
            "password1": "Clave-Segura-987", "password2": "Clave-Segura-987", "usable_password": "true",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(roles_de(User.objects.get(username="tec1")), [MANAGER, TECNICO])
        self.assertContains(self.client.get(reverse("admin:auth_user_changelist")), "Manager, Técnico")
        self.assertEqual(set(ROLES), {MANAGER, ADMINISTRADOR, TECNICO})
