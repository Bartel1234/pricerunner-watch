#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command -v docker >/dev/null || { echo 'Docker mangler.'; exit 1; }
command -v openssl >/dev/null || { echo 'OpenSSL mangler (brug Compose med egen APP_PASSWORD).'; exit 1; }
if docker container inspect pricerunner-watch >/dev/null 2>&1; then
  echo 'Containeren findes allerede. Ingen ændringer foretaget. Se opdatering i README.md.'
  exit 1
fi
TASK_DATA_PATH="${DATA_PATH:-/mnt/user/appdata/pricerunner-watch}"
TASK_PORT="${WEB_PORT:-8788}"
mkdir -p -- "$TASK_DATA_PATH"
if [ ! -f .env ]; then
  umask 077
  printf 'APP_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env
fi
# Only read the generated key; never execute an .env file as shell code.
TASK_PASSWORD="$(sed -n 's/^APP_PASSWORD=//p' .env | head -n 1)"
if [ "${#TASK_PASSWORD}" -lt 16 ]; then echo 'APP_PASSWORD i .env skal have mindst 16 tegn.'; exit 1; fi
if [ "${SKIP_BUILD:-0}" != 1 ]; then
  docker build --pull -t pricerunner-watch:0.1.0-beta.3 .
fi
TASK_UID="$(docker run --rm --entrypoint id pricerunner-watch:0.1.0-beta.3 -u)"
TASK_GID="$(docker run --rm --entrypoint id pricerunner-watch:0.1.0-beta.3 -g)"
# Change the dedicated directory itself only; no recursive changes to unrelated files.
chown "$TASK_UID:$TASK_GID" "$TASK_DATA_PATH"
docker run -d --name pricerunner-watch --init --restart unless-stopped \
  --shm-size=1g --cap-drop=ALL --security-opt=no-new-privileges:true \
  -p "$TASK_PORT:8788" --env-file .env -e DATA_DIR=/data \
  -v "$TASK_DATA_PATH:/data" \
  --label 'net.unraid.docker.managed=dockerman' \
  --label "net.unraid.docker.webui=http://[IP]:[PORT:$TASK_PORT]/" \
  pricerunner-watch:0.1.0-beta.3
printf '\nInstalleret. Åbn http://DIN-UNRAID-IP:%s\nBruger: admin\nAdgangskoden står i .env i denne mappe.\n' "$TASK_PORT"
