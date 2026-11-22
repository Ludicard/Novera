from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.usuarios.roles import (
    ADMINISTRADOR, COOKIE_ULTIMO_ROL, MANAGER, SESION_ROL, TECNICO, asignar_roles, roles_de, roles_disponibles,
)
from apps.usuarios.tests.utils import entrar_como

CLAVE = "clave-segura-123"


class RolesTests(TestCase):
    def test_los_tres_roles_existen(self):
        self.assertTrue({"Administrador", "Manager", "Técnico"} <= set(Group.objects.values_list("name", flat=True)))

    def test_superusuario_siempre_es_administrador_sin_escribir(self):
        admin = User.objects.create_superuser("jefe", "j@x.test", CLAVE)
        self.assertEqual(roles_de(admin), [ADMINISTRADOR])
        self.assertFalse(admin.groups.exists())  # solo lectura: no toca la base de datos

    def test_varios_roles(self):
        u = User.objects.create_user("ana", password=CLAVE)
        asignar_roles(u, [TECNICO, MANAGER])
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
        self.assertEqual([o["clave"] for o in r.context["opciones"]], [TECNICO])

    def test_administrador_sugerido_y_ultimo_rol_recordado(self):
        asignar_roles(self.u, [ADMINISTRADOR])
        r = self.iniciar_sesion()
        self.assertEqual([o["clave"] for o in r.context["opciones"] if o["sugerido"]], [ADMINISTRADOR])
        r = self.client.post(self.elegir, {"rol": TECNICO})
        self.assertEqual(r.cookies[COOKIE_ULTIMO_ROL].value, TECNICO)
        self.client.post(reverse("logout"))
        r = self.iniciar_sesion()
        sugerido = [o for o in r.context["opciones"] if o["sugerido"]][0]
        self.assertEqual((sugerido["clave"], sugerido["ultimo"]), (TECNICO, True))

    def test_sin_elegir_no_entra_y_luego_vuelve_a_donde_iba(self):
        asignar_roles(self.u, [MANAGER])
        self.client.force_login(self.u)
        r = self.client.get(reverse("facturas:lista") + "?estado=VENCIDA")
        self.assertRedirects(r, self.elegir + "?siguiente=%2Ffacturas%2F%3Festado%3DVENCIDA")
        r = self.client.post(self.elegir, {"rol": MANAGER, "siguiente": "/facturas/?estado=VENCIDA"})
        self.assertRedirects(r, "/facturas/?estado=VENCIDA")

    def test_post_sin_rol_vuelve_a_la_pagina_del_formulario(self):
        asignar_roles(self.u, [MANAGER])
        self.client.force_login(self.u)
        r = self.client.post(reverse("clientes:nuevo"), {"nombre": "X"}, HTTP_REFERER="http://testserver/clientes/nuevo/")
        self.assertRedirects(r, self.elegir + "?siguiente=%2Fclientes%2Fnuevo%2F", fetch_redirect_response=False)

    def test_no_vuelve_a_salir_ni_a_entrar(self):
        asignar_roles(self.u, [MANAGER])
        self.client.force_login(self.u)
        for malo in ["/cuentas/logout/", "/admin/logout/", "/cuentas/login/", "https://malicioso.test/"]:
            r = self.client.post(self.elegir, {"rol": MANAGER, "siguiente": malo})
            self.assertEqual(r.url, reverse("inicio"), malo)

    def test_no_puede_elegir_un_rol_sin_acceso(self):
        asignar_roles(self.u, [TECNICO])
        self.client.force_login(self.u)
        self.assertEqual(self.client.post(self.elegir, {"rol": ADMINISTRADOR}).status_code, 400)
        self.assertNotIn(SESION_ROL, self.client.session)

    def test_cada_inicio_de_sesion_vuelve_a_preguntar(self):
        asignar_roles(self.u, [MANAGER])
        self.iniciar_sesion()
        self.client.post(self.elegir, {"rol": MANAGER})
        self.client.post(reverse("logout"))
        self.assertEqual(self.iniciar_sesion().request["PATH_INFO"], self.elegir)

    def test_cambiar_de_rol_marca_el_actual_y_permite_volver(self):
        entrar_como(self.client, self.u, MANAGER, roles=[MANAGER, TECNICO])
        r = self.client.get(self.elegir + "?siguiente=/facturas/")
        self.assertEqual([o["clave"] for o in r.context["opciones"] if o["actual"]], [MANAGER])
        self.assertContains(r, "Volver sin cambiar")
        self.assertContains(r, 'class="topbar"')

    def test_login_ya_iniciado_redirige(self):
        entrar_como(self.client, self.u, MANAGER)
        self.assertEqual(self.client.get(reverse("login")).status_code, 302)

    def test_paginas_de_contrasena_funcionan(self):
        entrar_como(self.client, self.u, MANAGER)
        r = self.client.get(reverse("password_change"))
        self.assertContains(r, "Cambiar mi contraseña")
        r = self.client.post(reverse("password_change"), {
            "old_password": CLAVE, "new_password1": "Otra-Clave-998", "new_password2": "Otra-Clave-998",
        }, follow=True)
        self.assertContains(r, "Contraseña cambiada")

    def test_cuenta_sin_rol(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "aún no tiene un rol", status_code=403)
        self.assertEqual(self.client.get("/salud/").status_code, 200)
        r = self.client.post(reverse("logout"))
        self.assertEqual(r.status_code, 302)

    def test_logout_del_admin_sin_rol_elegido(self):
        jefe = User.objects.create_superuser("jefe", "j@x.test", CLAVE)
        self.client.force_login(jefe)
        self.client.post(reverse("admin:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_superusuario_entra_al_admin_sin_elegir_rol(self):
        jefe = User.objects.create_superuser("jefe", "j@x.test", CLAVE)
        self.client.force_login(jefe)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
