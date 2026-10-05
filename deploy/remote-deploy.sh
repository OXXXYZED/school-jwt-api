#!/usr/bin/env bash
# Runs on the server; invoked by .github/workflows/deploy.yml after it uploads the new source
# to ~/school-api/src.new. Picks the deploy target and hands over to it:
#   host-caddy  the server's own systemd Caddy already serves other sites on 80/443: run the app
#               as a systemd service behind it (deploy/host-caddy-deploy.sh);
#   compose     otherwise: Docker Compose with the bundled Caddy (deploy/compose-deploy.sh).
# DEPLOY_TARGET=auto (default) picks host-caddy when a caddy systemd service is active.
# The optional demo password is read from stdin.
set -euo pipefail

: "${DOMAIN:?DOMAIN is required}"
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Invalid DOMAIN: $DOMAIN" >&2
  exit 1
fi
APP_PORT="${APP_PORT:-8800}"
if [[ ! "$APP_PORT" =~ ^[0-9]+$ ]]; then
  echo "Invalid APP_PORT: $APP_PORT" >&2
  exit 1
fi
DEMO_PASSWORD=""
if [ ! -t 0 ]; then
  DEMO_PASSWORD="$(cat)"
fi
export DOMAIN APP_PORT DEMO_PASSWORD

target="${DEPLOY_TARGET:-auto}"
if [ "$target" = auto ]; then
  if systemctl is-active --quiet caddy 2>/dev/null; then target=host-caddy; else target=compose; fi
fi
echo "==> Deploy target: $target"

here="$(cd "$(dirname "$0")" && pwd)"
case "$target" in
  host-caddy) exec bash "$here/host-caddy-deploy.sh" ;;
  compose) exec bash "$here/compose-deploy.sh" ;;
  *) echo "Unknown DEPLOY_TARGET: $target (expected auto, compose or host-caddy)" >&2; exit 1 ;;
esac
