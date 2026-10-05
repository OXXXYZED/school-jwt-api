#!/usr/bin/env bash
# Read-only server checks: Actions → Deploy → Run workflow → mode "diagnose".
# The repository is public and so are its Actions logs: print facts, never configs or secrets.
set -uo pipefail

section() { printf '\n== %s\n' "$*"; }

section "System"
grep -m1 "^PRETTY_NAME=" /etc/os-release | cut -d= -f2- | tr -d '"'
echo "user: $(id -un) (uid $(id -u))"

section "Docker"
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker compose version 2>&1 | head -1
else
  echo "not installed"
fi

section "Listeners on ports 80/443"
ss -Hltnp '( sport = :80 or sport = :443 )' 2>/dev/null || echo "ss unavailable"

section "Containers publishing 80/443"
if command -v docker >/dev/null 2>&1; then
  docker ps --filter publish=80 --filter publish=443 --format '{{.Names}}  {{.Image}}  {{.Ports}}'
fi

section "Caddy"
if command -v caddy >/dev/null 2>&1; then caddy version; else echo "binary: not found"; fi
echo "systemd unit: $(systemctl is-active caddy 2>/dev/null || true)"
if [ -r /etc/caddy/Caddyfile ]; then
  echo "/etc/caddy/Caddyfile: site addresses and imports only"
  grep -nE '^[^[:space:]#][^{]*\{[[:space:]]*$|^[[:space:]]*import[[:space:]]' /etc/caddy/Caddyfile || true
fi

section "Config mentioning ${DOMAIN:-<DOMAIN unset>}"
if [ -n "${DOMAIN:-}" ] && [ -d /etc/caddy ]; then
  parent="${DOMAIN#*.}"
  grep -rlE "(^|[[:space:],])(${DOMAIN//./\\.}|\\*\\.${parent//./\\.})([[:space:],:{]|$)" /etc/caddy 2>/dev/null || echo "none"
fi

section "Runtime"
python3 --version 2>/dev/null || echo "python3: not found"
echo "python3-venv: $(dpkg-query -W -f='${Status}' python3-venv 2>/dev/null || echo 'not installed')"
free -m | awk 'NR<=2'
df -h / | awk 'NR==2 {print "disk /: " $4 " free of " $2}'
echo "port ${APP_PORT:-8800} on localhost: $(ss -Hltn "sport = :${APP_PORT:-8800}" | grep -q . && echo 'in use' || echo 'free')"

section "Firewall"
ufw status 2>/dev/null | head -8 || true

section "This app"
ls -A ~/school-api 2>/dev/null || echo "not deployed yet"
