#!/usr/bin/env bash
# Deploy target "host-caddy": for a server whose own systemd Caddy already serves other sites on
# 80/443. Installs no Docker and no second proxy:
#   - the app runs from a venv as the systemd service "school-api" (user school-api) on
#     127.0.0.1:$APP_PORT;
#   - Caddy gets one site file, /etc/caddy/$DOMAIN.caddy, imported from /etc/caddy/Caddyfile.
#     The change is validated first and applied with a graceful reload; on any failure the
#     previous Caddy config is restored, so other sites keep working.
# Called by deploy/remote-deploy.sh with DOMAIN, APP_PORT and the optional DEMO_PASSWORD exported.
#
# Layout:  /opt/school-api/{src,venv,secret.env,app.env,manage}   /var/lib/school-api/db.sqlite3
# Admin:   /opt/school-api/manage <command>   (e.g. createsuperuser), runs as the service user
set -euo pipefail

: "${DOMAIN:?DOMAIN is required}" "${APP_PORT:?APP_PORT is required}"
DEMO_PASSWORD="${DEMO_PASSWORD:-}"
STAGE="$HOME/school-api/src.new"
APP_DIR=/opt/school-api
DATA_DIR=/var/lib/school-api
SERVICE=school-api
APP_USER=school-api
CADDYFILE=/etc/caddy/Caddyfile
SITE_FILE="/etc/caddy/$DOMAIN.caddy"

log() { printf '==> %s\n' "$*"; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

app_ready() {
  python3 -c 'import sys, urllib.request as u; u.urlopen(u.Request(f"http://127.0.0.1:{sys.argv[2]}/api/docs/", headers={"Host": sys.argv[1]}), timeout=3)' \
    "$DOMAIN" "$APP_PORT" 2>/dev/null
}

# The app port must be free, or held by this very service (a redeploy).
port_available() {
  local listeners main_pid
  listeners="$(ss -Hltnp "sport = :$APP_PORT")"
  [ -z "$listeners" ] && return 0
  main_pid="$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || echo 0)"
  [ "$main_pid" != 0 ] && grep -q "pid=$main_pid," <<<"$listeners"
}

log "Checking prerequisites"
[ "$(id -u)" -eq 0 ] || die "The host-caddy target needs root (systemd unit, Caddy config)."
systemctl is-active --quiet caddy || die "The caddy service is not active."
command -v caddy >/dev/null || die "caddy binary not found."
python3 -c 'import venv, ensurepip' 2>/dev/null || die "python3 venv is missing (apt install python3-venv)."
[ -d "$STAGE" ] || die "No uploaded release at $STAGE."
if ! port_available; then
  ss -Hltnp "sport = :$APP_PORT" >&2
  die "Port $APP_PORT is used by another process; set the DEPLOY_APP_PORT variable to a free port."
fi

# Caddy first: if its config is rejected, nothing else on the server has been changed yet.
# (On the very first deploy the site answers 502 until the app below is up.)
log "Configuring Caddy for $DOMAIN"
site_conf="$DOMAIN {
	encode zstd gzip
	reverse_proxy 127.0.0.1:$APP_PORT
}"
import_line="import $SITE_FILE"
if [ -f "$SITE_FILE" ] && [ "$(cat "$SITE_FILE")" = "$site_conf" ] && grep -qxF "$import_line" "$CADDYFILE"; then
  log "Caddy config is already up to date"
else
  backup="/etc/caddy/.school-api-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup"
  cp -a "$CADDYFILE" "$backup/Caddyfile"
  if [ -f "$SITE_FILE" ]; then cp -a "$SITE_FILE" "$backup/site.caddy"; fi
  restore_caddy() {
    cp -a "$backup/Caddyfile" "$CADDYFILE"
    if [ -f "$backup/site.caddy" ]; then cp -a "$backup/site.caddy" "$SITE_FILE"; else rm -f "$SITE_FILE"; fi
  }

  printf '%s\n' "$site_conf" >"$SITE_FILE"
  chmod 644 "$SITE_FILE"
  grep -qxF "$import_line" "$CADDYFILE" || printf '\n%s\n' "$import_line" >>"$CADDYFILE"

  if ! caddy validate --config "$CADDYFILE" --adapter caddyfile >"$backup/validate.log" 2>&1; then
    restore_caddy
    grep -iE 'error|invalid' "$backup/validate.log" | tail -n 5 >&2 || true
    die "The new Caddy config did not validate; the previous config was restored (other sites unaffected)."
  fi
  if ! systemctl reload caddy; then
    restore_caddy
    systemctl reload caddy || true
    die "Caddy reload failed; the previous config was restored."
  fi
  log "Caddy reloaded (backup of the previous config: $backup)"
fi

log "Preparing user, directories and environment"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 755 -o root -g root "$APP_DIR"
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$DATA_DIR"
# The secret is generated once and kept; everything else is rewritten on each deploy.
if [ ! -f "$APP_DIR/secret.env" ]; then
  (umask 077 && printf 'DJANGO_SECRET_KEY=%s\n' "$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')" >"$APP_DIR/secret.env")
fi
chown root:"$APP_USER" "$APP_DIR/secret.env"
chmod 640 "$APP_DIR/secret.env"
cat >"$APP_DIR/app.env" <<EOF
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$DOMAIN
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DJANGO_NUM_PROXIES=1
DJANGO_SQLITE_PATH=$DATA_DIR/db.sqlite3
PYTHONDONTWRITEBYTECODE=1
EOF
cat >"$APP_DIR/manage" <<EOF
#!/bin/sh
# Django management commands as the service user, e.g.: $APP_DIR/manage createsuperuser
set -a
. $APP_DIR/secret.env
. $APP_DIR/app.env
set +a
cd "\${APP_SRC:-$APP_DIR/src}" && exec runuser -u $APP_USER -- $APP_DIR/venv/bin/python manage.py "\$@"
EOF
chmod 755 "$APP_DIR/manage"

log "Building the new release"
rm -rf "$APP_DIR/src.new"
mv "$STAGE" "$APP_DIR/src.new"
chown -R root:root "$APP_DIR/src.new"
chmod -R u+rwX,go+rX,go-w "$APP_DIR/src.new"
[ -x "$APP_DIR/venv/bin/python" ] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --disable-pip-version-check -r "$APP_DIR/src.new/requirements.txt"
(
  set -a
  # shellcheck source=/dev/null
  . "$APP_DIR/secret.env"
  # shellcheck source=/dev/null
  . "$APP_DIR/app.env"
  set +a
  cd "$APP_DIR/src.new"
  "$APP_DIR/venv/bin/python" manage.py check
  "$APP_DIR/venv/bin/python" manage.py collectstatic --noinput -v 0
)
APP_SRC="$APP_DIR/src.new" "$APP_DIR/manage" migrate --noinput

log "Switching to the new release"
rm -rf "$APP_DIR/src.old" "$APP_DIR/src.failed"
if [ -d "$APP_DIR/src" ]; then mv "$APP_DIR/src" "$APP_DIR/src.old"; fi
mv "$APP_DIR/src.new" "$APP_DIR/src"

cat >"/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=School API (Django + gunicorn) for $DOMAIN
After=network.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/src
EnvironmentFile=$APP_DIR/secret.env
EnvironmentFile=$APP_DIR/app.env
# One process keeps the in-memory login throttle counters consistent; threads add concurrency.
ExecStart=$APP_DIR/venv/bin/gunicorn config.wsgi --bind 127.0.0.1:$APP_PORT --workers 1 --threads 4 --no-control-socket --access-logfile -
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
systemctl restart "$SERVICE"

log "Waiting for the app on 127.0.0.1:$APP_PORT"
for _ in $(seq 1 30); do
  app_ready && break
  sleep 1
done
if ! app_ready; then
  journalctl -u "$SERVICE" -n 40 --no-pager >&2 || true
  if [ -d "$APP_DIR/src.old" ]; then
    log "Rolling back to the previous release"
    mv "$APP_DIR/src" "$APP_DIR/src.failed"
    mv "$APP_DIR/src.old" "$APP_DIR/src"
    systemctl restart "$SERVICE"
  fi
  die "The app did not become ready."
fi

if [ -n "$DEMO_PASSWORD" ]; then
  log "Seeding demo users (existing users are left untouched)"
  "$APP_DIR/manage" seed_demo --password "$DEMO_PASSWORD"
fi

rm -rf "$APP_DIR/src.old"
rmdir "$HOME/school-api" 2>/dev/null || true
log "Deployed: https://$DOMAIN/api/docs/"
