from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.usuarios.roles import ADMINISTRADOR, MANAGER, TECNICO, asignar_roles, roles_de
from apps.usuarios.tests.utils import entrar_como

CLAVE = "clave-segura-123"


class GestionUsuariosTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("jefa", password=CLAVE, first_name="Jefa")
        entrar_como(self.client, self.admin, ADMINISTRADOR)

    def datos(self, u, **extra):
        d = {"accion": "datos", "first_name": u.first_name or "Nombre", "last_name": "", "username": u.username,
             "email": "", "roles": roles_de(u), "activo": "on" if u.is_active else ""}
        d.update(extra)
        return d

    def test_crear_cuenta_en_un_solo_paso(self):
        r = self.client.post(reverse("usuarios:nueva"), {
            "first_name": "Luis", "last_name": "Paz", "username": "luis", "email": "luis@x.test",
            "roles": [TECNICO, MANAGER], "password1": "Clave-Segura-987", "password2": "Clave-Segura-987",
        })
        self.assertRedirects(r, reverse("usuarios:lista"))
        u = User.objects.get(username="luis")
        self.assertEqual(roles_de(u), [MANAGER, TECNICO])
        self.assertTrue(u.check_password("Clave-Segura-987"))
        self.assertFalse(u.is_staff)

    def test_validaciones_al_crear(self):
        r = self.client.post(reverse("usuarios:nueva"), {
            "first_name": "Luis", "username": "JEFA", "roles": [], "password1": "123", "password2": "456",
        })
        errores = r.context["form"].errors
        self.assertIn("username", errores)
        self.assertIn("roles", errores)
        self.assertIn("password2", errores)

    def test_editar_roles_y_desactivar(self):
        otro = User.objects.create_user("tec", password=CLAVE, first_name="Tec")
        asignar_roles(otro, [TECNICO])
        r = self.client.post(reverse("usuarios:editar", args=[otro.pk]), self.datos(otro, roles=[MANAGER], activo=""))
        self.assertRedirects(r, reverse("usuarios:lista"))
        otro.refresh_from_db()
        self.assertEqual((roles_de(otro), otro.is_active), ([MANAGER], False))

    def test_no_puede_quitarse_administrador_ni_desactivarse(self):
        otro = User.objects.create_user("otro", password=CLAVE)
        asignar_roles(otro, [ADMINISTRADOR])  # hay otro admin, así que la regla es la de «a ti mismo»
        r = self.client.post(reverse("usuarios:editar", args=[self.admin.pk]), self.datos(self.admin, roles=[MANAGER]))
        self.assertContains(r, "No puedes quitarte el rol Administrador")
        self.client.post(reverse("usuarios:editar", args=[self.admin.pk]), self.datos(self.admin, activo=""))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        r = self.client.post(reverse("usuarios:activar", args=[self.admin.pk]), follow=True)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_desactivar_a_otro_administrador_si_quedan_mas(self):
        otro = User.objects.create_user("otro", password=CLAVE)
        asignar_roles(otro, [ADMINISTRADOR])
        self.client.post(reverse("usuarios:activar", args=[otro.pk]))
        otro.refresh_from_db()
        self.assertFalse(otro.is_active)

    def test_regla_del_ultimo_administrador(self):
        from apps.usuarios.forms import CuentaForm

        asignar_roles(self.admin, [ADMINISTRADOR])
        manager = User.objects.create_user("man", password=CLAVE)
        # Defensa en profundidad: aunque el cambio lo pidiera otra cuenta, no se puede dejar sin Administradores
        form = CuentaForm(self.datos(self.admin, roles=[MANAGER]), instance=self.admin, actor=manager)
        self.assertFalse(form.is_valid())
        self.assertIn("Debe quedar al menos un Administrador activo.", form.non_field_errors())

    def test_superusuario_solo_lo_edita_otro_superusuario(self):
        su = User.objects.create_superuser("root", "r@x.test", CLAVE)
        r = self.client.get(reverse("usuarios:editar", args=[su.pk]))
        self.assertRedirects(r, reverse("usuarios:lista"))
        self.client.post(reverse("usuarios:activar", args=[su.pk]))
        su.refresh_from_db()
        self.assertTrue(su.is_active)

    def test_restablecer_contrasena(self):
        otro = User.objects.create_user("tec", password=CLAVE)
        asignar_roles(otro, [TECNICO])
        r = self.client.post(reverse("usuarios:editar", args=[otro.pk]), {
            "accion": "password", "password1": "Nueva-Clave-555", "password2": "Nueva-Clave-555",
        })
        self.assertRedirects(r, reverse("usuarios:editar", args=[otro.pk]))
        otro.refresh_from_db()
        self.assertTrue(otro.check_password("Nueva-Clave-555"))

    def test_solo_el_rol_administrador_gestiona_usuarios(self):
        tec = User.objects.create_user("tec", password=CLAVE)
        entrar_como(self.client, tec, TECNICO)
        self.assertRedirects(self.client.get(reverse("usuarios:lista")), reverse("dashboard"))
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("usuarios:lista"))
        # Un Administrador que eligió trabajar como Técnico tampoco
        entrar_como(self.client, self.admin, TECNICO, roles=[ADMINISTRADOR])
        self.assertRedirects(self.client.get(reverse("usuarios:lista")), reverse("dashboard"))

    def test_lista_y_busqueda(self):
        r = self.client.get(reverse("usuarios:lista") + "?q=jef")
        self.assertContains(r, "jefa")
        self.assertEqual(self.client.get(reverse("usuarios:lista") + "?estado=desactivadas").status_code, 200)

    def test_admin_django_solo_superusuarios(self):
        r = self.client.get(reverse("dashboard"))
        self.assertNotContains(r, "Admin avanzado")
        su = User.objects.create_superuser("root", "r@x.test", CLAVE)
        entrar_como(self.client, su, ADMINISTRADOR)
        self.assertContains(self.client.get(reverse("dashboard")), "Admin avanzado")


class ManagerTecnicoSinAdminTests(TestCase):
    """Una cuenta con acceso solo a Manager y Técnico no ve ni puede usar nada de administración."""

    def setUp(self):
        self.u = User.objects.create_user("p2", password=CLAVE)
        asignar_roles(self.u, [MANAGER, TECNICO])
        self.client.force_login(self.u)

    def test_selector_sin_administrador(self):
        r = self.client.get(reverse("usuarios:elegir_rol"))
        self.assertEqual([o["clave"] for o in r.context["opciones"]], [MANAGER, TECNICO])
        self.assertNotContains(r, 'value="administrador"')
        self.assertEqual(self.client.post(reverse("usuarios:elegir_rol"), {"rol": ADMINISTRADOR}).status_code, 400)

    def test_sin_enlaces_ni_acceso_de_administracion(self):
        for rol in (MANAGER, TECNICO):
            self.client.post(reverse("usuarios:elegir_rol"), {"rol": rol})
            r = self.client.get(reverse("dashboard"))
            self.assertNotContains(r, "Admin avanzado")
            self.assertNotContains(r, "Usuarios y accesos")
            self.assertNotContains(r, 'href="/admin/')
            self.assertRedirects(self.client.get(reverse("usuarios:lista")), reverse("dashboard"))
            self.assertEqual(self.client.get("/admin/").status_code, 302)  # al login del admin: no es staff

    def test_alta_desde_novera_guarda_exactamente_esos_roles(self):
        admin = User.objects.create_user("jefa", password=CLAVE, first_name="Jefa")
        entrar_como(self.client, admin, ADMINISTRADOR)
        self.client.post(reverse("usuarios:nueva"), {
            "first_name": "P", "username": "p3", "roles": [MANAGER, TECNICO],
            "password1": "Clave-Segura-987", "password2": "Clave-Segura-987",
        })
        nuevo = User.objects.get(username="p3")
        self.assertEqual(roles_de(nuevo), [MANAGER, TECNICO])
        self.assertFalse(nuevo.is_staff or nuevo.is_superuser)
