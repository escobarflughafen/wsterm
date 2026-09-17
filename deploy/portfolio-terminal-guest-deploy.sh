#!/bin/bash
# Portfolio Terminal guest instance — tmpfs portfolio data + public cache + anonymous Cloudflare Quick Tunnel.
#
#   portfolio-terminal-guest-deploy.sh init [ref]     clone and create .env with a random guest access token
#   portfolio-terminal-guest-deploy.sh deploy [ref]   build, start, and verify app + cloudflared
#   portfolio-terminal-guest-deploy.sh survey         show containers and storage
#   portfolio-terminal-guest-deploy.sh link           print the bearer guest URL (treat it as a password)
#   portfolio-terminal-guest-deploy.sh logs
#
# The public trycloudflare.com hostname is random and changes whenever the cloudflared container is recreated.

set -euo pipefail

REPO=${PT_REPO:-$HOME/git/portfolio-terminal.git}
ROOT=${PT_GUEST_ROOT:-/srv/portfolio-terminal-guest}
APP=$ROOT/app
DATA=$ROOT/data
PORT=${PT_GUEST_PORT:-8789}
BRANCH=${PT_GUEST_BRANCH:-main}
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.guest.yml)

ok()   { echo "[✓] $*"; }
warn() { echo "[~] $*"; }
die()  { echo "[!] $*" >&2; exit 1; }
env_get() { awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); value=$0} END {print value}' "$APP/.env" 2>/dev/null; }
compose() { (cd "$APP" && "${COMPOSE[@]}" "$@"); }
public_url() {
  local configured
  configured=$(env_get GUEST_PUBLIC_URL)
  if [ -n "$configured" ]; then printf '%s\n' "${configured%/}"; return; fi
  docker logs portfolio-terminal-guest-tunnel 2>&1 \
    | grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' | tail -1
}

cmd_init() {
  local ref=${1:-$BRANCH}
  mkdir -p "$ROOT" "$DATA/public-market"
  chmod 750 "$ROOT" "$DATA" "$DATA/public-market"
  if [ ! -d "$APP/.git" ]; then git clone -q -b "$ref" "$REPO" "$APP"; fi
  if [ ! -f "$APP/.env" ]; then
    local access; access=$(openssl rand -hex 32)
    sed -e 's|^COMPOSE_PROJECT_NAME=.*|COMPOSE_PROJECT_NAME=portfolio-terminal-guest|' \
        -e "s|^PORT=.*|PORT=$PORT|" \
        -e 's|^BIND_ADDR=.*|BIND_ADDR=127.0.0.1|' \
        -e "s|^DATA_PATH=.*|DATA_PATH=$DATA|" \
        -e "s|^APP_UID=.*|APP_UID=$(id -u)|" \
        -e "s|^APP_GID=.*|APP_GID=$(id -g)|" \
        -e 's|^APP_PASSWORD=.*|APP_PASSWORD=|' \
        -e 's|^FETCH_TIMES=.*|FETCH_TIMES=|' \
        -e "s|^GUEST_TOKEN=.*|GUEST_TOKEN=$access|" \
        "$APP/.env.example" > "$APP/.env"
    printf '\nGUEST_PUBLIC_URL=\n' >> "$APP/.env"
    chmod 600 "$APP/.env"
    ok "created $APP/.env with a random guest access token"
  else
    warn '.env already exists; left unchanged'
  fi
  ok "guest checkout $APP · localhost port $PORT · public cache $DATA/public-market"
}

wait_healthy() {
  local waited=0 state=''
  while [ "$waited" -lt 120 ]; do
    state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' portfolio-terminal-guest 2>/dev/null || echo missing)
    [ "$state" = healthy ] && return 0
    [ "$state" = unhealthy ] && break
    sleep 3; waited=$((waited + 3))
  done
  die "guest container is $state after ${waited}s"
}

verify() {
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/healthz")" = 200 ] || die 'healthz failed'
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")" = 401 ] || die 'guest endpoint is not token-protected'
  local token headers cookie
  token=$(env_get GUEST_TOKEN)
  headers=$(mktemp)
  curl -s -D "$headers" -o /dev/null "http://127.0.0.1:$PORT/?token=$token"
  cookie=$(awk 'BEGIN{IGNORECASE=1} /^set-cookie:/ {sub(/^[^:]*:[[:space:]]*/, ""); split($0,a,";"); print a[1]; exit}' "$headers")
  rm -f "$headers"
  [ -n "$cookie" ] || die 'token exchange did not set a session cookie'
  [ "$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $cookie" "http://127.0.0.1:$PORT/")" = 200 ] || die 'guest session cookie failed'
  [ "$(docker inspect -f '{{.State.Status}}' portfolio-terminal-guest-tunnel 2>/dev/null)" = running ] || die 'cloudflared is not running'
  local url waited=0
  while [ "$waited" -lt 60 ]; do
    url=$(public_url || true)
    [ -n "$url" ] && break
    sleep 2; waited=$((waited + 2))
  done
  [ -n "$url" ] || die 'cloudflared did not publish a Quick Tunnel URL'
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$url/healthz")" = 200 ] || die 'public tunnel health check failed'
  ok "guest auth, app health, and Quick Tunnel verified at $url"
}

cmd_deploy() {
  local ref=${1:-origin/$BRANCH}
  [ -d "$APP/.git" ] || die 'run init first'
  [ -f "$APP/.env" ] || die 'missing .env'
  [ -n "$(env_get GUEST_TOKEN)" ] || die 'GUEST_TOKEN is missing'
  git -C "$APP" fetch -q origin
  git -C "$APP" checkout -q --detach "$ref"
  local sha; sha=$(git -C "$APP" rev-parse --short HEAD)
  export TAG="guest-$sha"
  compose build -q portfolio
  compose up -d --remove-orphans
  wait_healthy
  verify
  ok "deployed guest $sha on 127.0.0.1:$PORT"
}

cmd_survey() {
  compose ps
  echo "Public cache: $(du -sh "$DATA/public-market" 2>/dev/null | cut -f1)  $DATA/public-market"
  echo 'Private portfolio data: container tmpfs /guest (erased when container stops)'
}

cmd_link() {
  local base token
  base=$(public_url || true); token=$(env_get GUEST_TOKEN)
  [ -n "$base" ] || die 'Quick Tunnel URL is not available; deploy first'
  [ -n "$token" ] || die 'GUEST_TOKEN is empty in .env'
  base=${base%/}
  printf '%s/?token=%s\n' "$base" "$token"
}

case "${1:-}" in
  init) cmd_init "${2:-}" ;;
  deploy) cmd_deploy "${2:-}" ;;
  survey) cmd_survey ;;
  link) cmd_link ;;
  logs) compose logs -f --tail=200 ;;
  *) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
