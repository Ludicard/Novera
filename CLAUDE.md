# Novera: guía para sesiones de Claude

Novera es una app Django (5.2, Python 3.13) para una empresa ecuatoriana de mantenimiento de ascensores. Gestiona facturas por cobrar (importadas de FactureroMovil), proformas, órdenes de trabajo, técnicos y equipos, con roles Administrador, Manager y Técnico. El detalle funcional está en `README.md`.

## Forma de trabajo con el dueño

- Implementar el cambio, ejecutar las pruebas y **hacer commit** en `main`.
- Ofrecer ejecutarlo en local para revisarlo.
- **Push solo cuando el dueño lo pida** («Haz el push para desplegarlo»). Un push a `main` despliega en producción.
- Responder en español.
- Pruebas locales: `DJANGO_DEBUG=1 .venv/bin/python manage.py test`. En local se usa SQLite y en CI y producción PostgreSQL 17. Evitar consultas que solo funcionen en SQLite.

## Acceso al VPS

- **Servidor:** Ubuntu 24.04, IP `2.25.95.81`, usuario `root`, puerto 22, solo con llave.
- **Llave:** `~/.ssh/novera_vps`. Solo existe en esta máquina; no copiarla a otros equipos. Para dar acceso desde otro equipo, crear allí una llave nueva y añadirla a `/root/.ssh/authorized_keys`.
- **Comando base** (no interactivo):

  ```bash
  ssh -i ~/.ssh/novera_vps -o BatchMode=yes root@2.25.95.81 '<comando>'
  ```

- **Comandos de Novera:** ejecutarlos como el usuario `novera` desde la carpeta del proyecto. El `.env` ya define `COMPOSE_FILE`, así que basta con `docker compose`.

  ```bash
  cd /opt/proyectos/Novera && sudo -u novera docker compose ps
  cd /opt/proyectos/Novera && sudo -u novera docker compose logs --tail 100 web
  cd /opt/proyectos/Novera && sudo -u novera docker compose exec -T web python manage.py <comando>
  ```

- **Salud:** `curl -s https://novera.aurelianova.tech/salud/` devuelve `ok`.

## Qué hay en el VPS

| Ruta / contenedor | Qué es |
|---|---|
| `/opt/proyectos/Novera` | Novera, con dueño el usuario `novera`, que está en el grupo docker |
| `novera-web-1` | Django + Gunicorn en el puerto 8000. Se une a la red `proxy_network` con el alias `novera-web` |
| `novera-db-1` | PostgreSQL 17, con datos reales de facturas |
| `/opt/proyectos/Novera/.env` | Secretos (modo 600): secret key, contraseña de la base de datos, dominio. **No mostrar su contenido** |
| `/opt/proyectos/nginx-proxy-manager` | Proxy de todo el VPS: puertos 80, 443 y 81 (panel). `novera.aurelianova.tech` apunta a `http://novera-web:8000` con SSL de Let's Encrypt. Se gestiona desde su panel web, no desde archivos |
| `/opt/proyectos/{Portafolio,portfolio,EMA,project-zomboid}` | **Otras apps del dueño. No tocarlas** (ni sus contenedores `portafolio-*` y `ema-*`) |

## Despliegue

- **Flujo normal:**
  1. Push a `main` en GitHub (`Ludicard/Novera`).
  2. CI ejecuta las pruebas contra PostgreSQL.
  3. Si pasan, el job `deploy` entra por SSH como `novera`. La llave de ese usuario tiene un *forced command*: solo puede ejecutar `/usr/local/bin/novera-deploy`, que hace `git reset --hard origin/main` y luego `deploy/deploy.sh` (reconstruye, espera al healthcheck y limpia imágenes).
- **Seguir un despliegue:** `gh run list --limit 1` y `gh run watch <id> --exit-status`.
- **Secretos de GitHub** (entorno `produccion`): `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`, y la variable `NOVERA_URL`.
- **Despliegue manual, solo en emergencias:** `cd /opt/proyectos/Novera && sudo -u novera ./deploy/deploy.sh`
- **No editar archivos dentro de `/opt/proyectos/Novera`.** Cada despliegue hace `git reset --hard` y borra esos cambios. Los cambios van por git. Excepción: el `.env`, que no está en git.
- `deploy/deploy.sh` no revierte solo. Si la app no queda sana, muestra los logs y sale con error, pero el contenedor nuevo queda en marcha. Para volver atrás: `git revert` del commit y push.

## Varias sesiones a la vez

Puede haber varias sesiones de Claude trabajando en paralelo en este repositorio y en el VPS:

- **Antes de tocar el VPS**, ver si hay algo en curso:

  ```bash
  ssh -i ~/.ssh/novera_vps -o BatchMode=yes root@2.25.95.81 'pgrep -af "deploy.sh|novera-deploy|pg_dump|pg_restore|manage.py" || echo libre'
  ```

  Además, `gh run list --limit 3` muestra si hay un despliegue de CI en marcha. No lanzar despliegues, restauraciones ni migraciones mientras otro esté en curso.
- `deploy.sh` usa el bloqueo `/tmp/novera-deploy.lock` (`flock`): dos despliegues no corren a la vez. El segundo espera hasta 10 minutos.
- **Bitácora:** cada operación manual en el VPS que cambie algo (reinicio, migración, restauración, cambio en el `.env` o en el proxy) se registra con una línea:

  ```bash
  echo "$(date '+%F %T') [sesión: <tema>] <qué se hizo>" | sudo tee -a /opt/proyectos/Novera/backups/OPERACIONES.log
  ```

  Leer las últimas líneas antes de empezar: `tail -20 /opt/proyectos/Novera/backups/OPERACIONES.log`.
- **Git local:** antes de hacer commit, revisar `git status` y `git log -3`. Otra sesión puede haber hecho commit o tener cambios sin confirmar. Hacer commit solo de los archivos propios (`git add <archivos>`, nunca `git add -A`). Antes de push: `git pull --rebase origin main`.
- Solo lectura (logs, `ps`, `/salud/`, consultas sin escritura) se puede hacer siempre sin coordinar.

## Respaldos

- **Script:** `deploy/backup.sh`. Hace `pg_dump` comprimido en `/opt/proyectos/Novera/backups/` y conserva los 30 últimos.
- **Respaldo manual:** `cd /opt/proyectos/Novera && sudo -u novera ./deploy/backup.sh`
- **⚠ No hay respaldo automático.** El cron del usuario `novera` está vacío (verificado el 2026-11-25). El último respaldo es del 2026-11-18. Hay que programarlo, con la aprobación del dueño:

  ```bash
  0 2 * * * cd /opt/proyectos/Novera && ./deploy/backup.sh >> backups/backup.log 2>&1
  ```

- **Hacer siempre un respaldo** antes de cualquier operación destructiva: migraciones que borren datos, restauraciones, importaciones masivas o borrados.
- **Restaurar** (destructivo, confirmar antes con el dueño):

  ```bash
  gunzip -c backups/<archivo>.sql.gz | sudo -u novera docker compose exec -T db psql -U <usuario> <base>
  ```

## Precauciones

- Producción tiene datos reales de clientes y facturas. No borrar ni modificar datos sin confirmarlo con el dueño.
- No mostrar ni copiar secretos: el `.env`, las llaves y las contraseñas de usuarios de la web.
- **Pendiente, a decidir por el dueño** (no cambiar sin su confirmación):
  - `ufw` está desactivado.
  - El panel del proxy (puerto 81) está abierto a internet.
  - SSH acepta root con contraseña. Valores efectivos (`sshd -T`): `permitrootlogin yes` y `passwordauthentication yes`. El valor viene de `/etc/ssh/sshd_config.d/50-cloud-init.conf`, que se lee antes que el `60-…` que lo desactiva.
- Un error que ya ocurrió: `FILE_UPLOAD_PERMISSIONS` en settings dejó los estáticos ilegibles y tumbó la app. Cualquier cambio en permisos, en el Dockerfile o en `entrypoint.sh` se prueba con `docker compose build` en local antes de hacer push.
