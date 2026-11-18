#!/bin/bash
# Despliegue en el VPS: trae main, reconstruye y espera a que la app esté sana.
# Lo ejecuta GitHub Actions por SSH en cada push a main (ver .github/workflows/ci.yml),
# o a mano: ./deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

exec 9>/tmp/novera-deploy.lock
flock -w 600 9 || { echo "Otro despliegue sigue en curso" >&2; exit 1; }

echo "==> $(date '+%F %T') desplegando"
git fetch --quiet origin main
git reset --hard --quiet origin/main
echo "    commit $(git log -1 --format='%h %s')"

docker compose up -d --build --remove-orphans

echo "==> esperando a que la app responda"
for _ in $(seq 1 40); do
  estado=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q web)" 2>/dev/null || echo "?")
  if [ "$estado" = "healthy" ]; then
    docker image prune -f >/dev/null
    echo "==> OK: Novera desplegada"
    exit 0
  fi
  sleep 5
done

echo "==> ERROR: la app no quedó sana. Últimos logs:" >&2
docker compose logs --tail 60 web >&2
exit 1
