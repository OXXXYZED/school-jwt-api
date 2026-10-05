#!/usr/bin/env bash
# Deploy target "compose": Docker Compose with the bundled Caddy (automatic HTTPS) for a server
# where nothing else listens on 80/443. Called by deploy/remote-deploy.sh with DOMAIN and the
# optional DEMO_PASSWORD exported. Idempotent: the first run bootstraps (Docker, .env with a
# generated secret), later runs update in place.
#
# Layout:  ~/school-api/.env   (persistent config, created once)
#          ~/school-api/src/   (current source; compose project "school-api")
set -euo pipefail

: "${DOMAIN:?DOMAIN is required}"
DEMO_PASSWORD="${DEMO_PASSWORD:-}"
APP_DIR="$HOME/school-api"

# Refuse to touch a server where something else (e.g. a host-level Caddy or nginx) already
# listens on 80/443: our Caddy container could not bind, and other sites must not be disturbed.
for port in 80 443; do
  if command -v ss >/dev/null 2>&1 && [ -n "$(ss -Hltn "sport = :$port")" ]; then
    owner="$(docker ps --filter "publish=$port" --format '{{.Names}}' 2>/dev/null || true)"
    if [ "$owner" != "school-api-caddy-1" ]; then
      echo "Port $port is already in use on this server; aborting before making any changes:" >&2
      ss -Hltnp "sport = :$port" >&2 || true
      exit 1
    fi
  fi
done

log() { printf '==> %s\n' "$*"; }

if ! command -v docker >/dev/null 2>&1; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "Docker is not installed. Install it or deploy as root to install it automatically." >&2
    exit 1
  fi
  log "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null

cd "$APP_DIR"
if [ ! -f .env ]; then
  log "Creating $APP_DIR/.env with a generated DJANGO_SECRET_KEY"
  (umask 077 && printf 'DOMAIN=%s\nDJANGO_SECRET_KEY=%s\n' "$DOMAIN" \
    "$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')" > .env)
fi
sed -i "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" .env

log "Switching to the new release"
rm -rf src.old
if [ -d src ]; then mv src src.old; fi
mv src.new src
ln -sfn ../.env src/.env
cd src

compose() { docker compose -p school-api "$@"; }

log "Building and starting containers"
compose up -d --build --remove-orphans

# The Caddyfile is bind-mounted by path; a running container keeps the replaced file's old
# content, so restart Caddy when the config actually changed.
if [ -f ../src.old/deploy/Caddyfile ] && ! cmp -s ../src.old/deploy/Caddyfile deploy/Caddyfile; then
  log "Caddyfile changed, restarting Caddy"
  compose restart caddy
fi

log "Waiting for the app (migrations run on start)"
for _ in $(seq 1 30); do
  if compose exec -T web python -c "import sys, urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/api/docs/', headers={'Host': sys.argv[1]}), timeout=3)" "$DOMAIN" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
if [ -z "${ready:-}" ]; then
  echo "App did not become ready; recent logs:" >&2
  compose logs --tail 50 web >&2
  exit 1
fi

if [ -n "$DEMO_PASSWORD" ]; then
  log "Seeding demo users (existing users are left untouched)"
  compose exec -T web python manage.py seed_demo --password "$DEMO_PASSWORD"
fi

rm -rf ../src.old
docker image prune -f >/dev/null
log "Deployed: https://$DOMAIN/api/docs/"
