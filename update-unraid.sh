#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command -v docker >/dev/null || { echo 'Docker mangler.'; exit 1; }
[ -f .env ] || { echo '.env mangler i kildemappen. Behold den fra installationen.'; exit 1; }
docker container inspect pricerunner-watch >/dev/null
TASK_DATA_PATH="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' pricerunner-watch)"
TASK_PORT="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8788/tcp") 0).HostPort}}' pricerunner-watch)"
[ -d "$TASK_DATA_PATH" ] && [ -n "$TASK_PORT" ] || { echo 'Datamappe eller port kunne ikke findes.'; exit 1; }
TASK_OLD_PASSWORD="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' pricerunner-watch | sed -n 's/^APP_PASSWORD=//p')"
TASK_PASSWORD="$(sed -n 's/^APP_PASSWORD=//p' .env | head -n 1)"
[ "$TASK_PASSWORD" = "$TASK_OLD_PASSWORD" ] || { echo '.env matcher ikke containerens adgangskode. Brug den oprindelige .env.'; exit 1; }
unset TASK_OLD_PASSWORD TASK_PASSWORD
# A failed build leaves the running installation intact.
docker build --pull -t pricerunner-watch:0.1.0-beta.3 .
TASK_STAMP="$(date -u +%Y%m%d-%H%M%S)"
TASK_OLD="pricerunner-watch-backup-$TASK_STAMP"
umask 077
mkdir -p backups
TASK_RENAMED=0
rollback() {
  trap - ERR
  if [ "$TASK_RENAMED" = 1 ]; then
    if docker container inspect pricerunner-watch >/dev/null 2>&1; then docker rm -f pricerunner-watch >/dev/null; fi
    docker rename "$TASK_OLD" pricerunner-watch
  fi
  docker start pricerunner-watch >/dev/null || true
  echo 'Opdatering fejlede. Den tidligere container er startet igen. Se fejl ovenfor.'
  exit 1
}
trap rollback ERR
docker stop pricerunner-watch >/dev/null
# Copy the entire stopped database directory, including SQLite WAL and credentials.
tar -czf "backups/data-$TASK_STAMP.tar.gz" -C "$TASK_DATA_PATH" .
docker rename pricerunner-watch "$TASK_OLD"
TASK_RENAMED=1
DATA_PATH="$TASK_DATA_PATH" WEB_PORT="$TASK_PORT" SKIP_BUILD=1 bash install-unraid.sh
TASK_HEALTHY=0
for TASK_ATTEMPT in $(seq 1 45); do
  TASK_STATUS="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' pricerunner-watch)"
  if [ "$TASK_STATUS" = healthy ]; then TASK_HEALTHY=1; break; fi
  sleep 1
done
[ "$TASK_HEALTHY" = 1 ]
trap - ERR
printf '\nOpdateret til beta.3. Backup: backups/data-%s.tar.gz\nTidligere container bevaret og stoppet: %s\n' "$TASK_STAMP" "$TASK_OLD"
