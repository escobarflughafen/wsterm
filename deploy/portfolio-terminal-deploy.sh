#!/bin/bash
# Portfolio Terminal — deployment helper for 10.10.20.3
#
#   portfolio-terminal-deploy.sh survey                 status of prod and dev
#   portfolio-terminal-deploy.sh init   <prod|dev>      clone, create .env (random password), data + backup dirs
#   portfolio-terminal-deploy.sh deploy <prod|dev> [ref] backup → checkout → build → up → verify → rollback on failure
#   portfolio-terminal-deploy.sh backup <prod|dev>      tar the data dir (keeps the newest 14)
#   portfolio-terminal-deploy.sh seed-dev               copy prod data into dev (dev restarted)
#   portfolio-terminal-deploy.sh promote                fast-forward main to what dev runs, then deploy prod
#   portfolio-terminal-deploy.sh logs   <prod|dev>
#   portfolio-terminal-deploy.sh self-update            install this script from the repo's main branch
#
# Instances:  prod = /srv/portfolio-terminal/app  branch main  port 8787  scheduled fetch 17:20 ET
#             dev  = ~/Workspaces/portfolio-terminal branch dev port 8788  live reload, no schedule
# Repo:       /home/aoi/git/portfolio-terminal.git  (clone: ssh://aoi@10.10.20.3/home/aoi/git/portfolio-terminal.git)
# Secrets live only in each instance's .env (mode 600). This script never prints them.

set -euo pipefail

REPO=/home/aoi/git/portfolio-terminal.git
declare -A DIR=([prod]=/srv/portfolio-terminal/app [dev]=/home/aoi/Workspaces/portfolio-terminal)
declare -A DATA=([prod]=/srv/portfolio-terminal/data [dev]=/home/aoi/Workspaces/portfolio-terminal/data)
declare -A BACKUPS=([prod]=/srv/portfolio-terminal/backups [dev]=/home/aoi/Workspaces/portfolio-terminal/backups)
declare -A BRANCH=([prod]=main [dev]=dev)
declare -A PORT=([prod]=8787 [dev]=8788)
declare -A PROJECT=([prod]=portfolio-terminal [dev]=portfolio-terminal-dev)
declare -A FETCH=([prod]=17:20 [dev]=)
KEEP_BACKUPS=14
HEALTH_TIMEOUT=120

banner()  { echo ""; echo "=========================================="; echo "  $*"; echo "=========================================="; }
section() { echo ""; echo "--- $* ---"; }
ok()      { echo "[✓] $*"; }
warn()    { echo "[~] $*"; }
bad()     { echo "[!] $*"; }
die()     { bad "$*"; exit 1; }

instance() {
  case "${1:-}" in prod|dev) echo "$1" ;; *) die "Instance must be prod or dev" ;; esac
}

compose() {  # compose <inst> <args...>
  local inst=$1; shift
  local files=(-f docker-compose.yml)
  [ "$inst" = dev ] && files+=(-f docker-compose.dev.yml)
  (cd "${DIR[$inst]}" && docker compose "${files[@]}" "$@")
}

env_get() {  # env_get <inst> <KEY>  (value only, not echoed by callers)
  grep -E "^$2=" "${DIR[$1]}/.env" 2>/dev/null | tail -1 | cut -d= -f2-
}

container() { echo "${PROJECT[$1]}"; }

# ------------------------------------------------------------------ init
cmd_init() {
  local inst; inst=$(instance "${1:-}")
  banner "INIT ${inst^^}"
  local parent; parent=$(dirname "${DIR[$inst]}")
  if [ "$inst" = prod ] && [ ! -w /srv/portfolio-terminal ]; then
    die "/srv/portfolio-terminal is missing or not writable. Run once:
    sudo install -d -o $(id -un) -g $(id -gn) -m 750 /srv/portfolio-terminal"
  fi
  mkdir -p "$parent"

  section "Repository"
  if [ -d "${DIR[$inst]}/.git" ]; then
    ok "already cloned: ${DIR[$inst]} ($(git -C "${DIR[$inst]}" rev-parse --short HEAD))"
  else
    git clone -q -b "${BRANCH[$inst]}" "$REPO" "${DIR[$inst]}"
    ok "cloned ${BRANCH[$inst]} into ${DIR[$inst]}"
  fi

  section "Data directories"
  mkdir -p "${DATA[$inst]}" "${BACKUPS[$inst]}"
  chmod 750 "${DATA[$inst]}" "${BACKUPS[$inst]}"
  ok "data    ${DATA[$inst]}"
  ok "backups ${BACKUPS[$inst]}"

  section "Environment (.env)"
  local envf="${DIR[$inst]}/.env"
  if [ -f "$envf" ]; then
    ok ".env exists (left unchanged)"
  else
    local pw; pw=$(openssl rand -base64 36 | tr -d '/+=\n' | cut -c1-32)
    sed -e "s|^COMPOSE_PROJECT_NAME=.*|COMPOSE_PROJECT_NAME=${PROJECT[$inst]}|" \
        -e "s|^PORT=.*|PORT=${PORT[$inst]}|" \
        -e "s|^BIND_ADDR=.*|BIND_ADDR=0.0.0.0|" \
        -e "s|^DATA_PATH=.*|DATA_PATH=${DATA[$inst]}|" \
        -e "s|^APP_UID=.*|APP_UID=$(id -u)|" \
        -e "s|^APP_GID=.*|APP_GID=$(id -g)|" \
        -e "s|^APP_PASSWORD=.*|APP_PASSWORD=${pw}|" \
        -e "s|^FETCH_TIMES=.*|FETCH_TIMES=${FETCH[$inst]}|" \
        -e "s|^FORWARDED_ALLOW_IPS=.*|FORWARDED_ALLOW_IPS=127.0.0.1|" \
        "${DIR[$inst]}/.env.example" > "$envf"
    chmod 600 "$envf"
    ok ".env created (mode 600). Password: grep APP_PASSWORD ${envf}"
  fi
}

# ------------------------------------------------------------------ backup
cmd_backup() {
  local inst; inst=$(instance "${1:-}")
  [ -d "${DATA[$inst]}" ] || die "No data dir for $inst"
  mkdir -p "${BACKUPS[$inst]}"
  local file="${BACKUPS[$inst]}/portfolio-${inst}-$(date +%Y%m%d-%H%M%S).tgz"
  tar czf "$file" -C "${DATA[$inst]}" --exclude=./exports/staging --exclude=./market/fetch_progress.json .
  chmod 640 "$file"
  ok "backup $(du -h "$file" | cut -f1)  $file"
  ls -1t "${BACKUPS[$inst]}"/portfolio-"${inst}"-*.tgz 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
}

# ------------------------------------------------------------------ verify
wait_healthy() {
  local inst=$1 name; name=$(container "$inst")
  local waited=0 state=""
  while [ $waited -lt $HEALTH_TIMEOUT ]; do
    state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || echo missing)
    [ "$state" = healthy ] && return 0
    [ "$state" = unhealthy ] && break
    if [ "$(docker inspect -f '{{.RestartCount}}' "$name" 2>/dev/null || echo 0)" -gt 0 ]; then state="crash-looping"; break; fi
    sleep 3; waited=$((waited + 3))
  done
  bad "container $name is $state after ${waited}s"
  return 1
}

verify() {
  local inst=$1 port=${PORT[$1]} fails=0
  local user pw; user=$(env_get "$inst" APP_USER); pw=$(env_get "$inst" APP_PASSWORD)
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/healthz" || true)
  [ "$code" = 200 ] && ok "healthz 200" || { bad "healthz $code"; fails=$((fails + 1)); }
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/" || true)
  [ "$code" = 401 ] && ok "auth enforced (401 without credentials)" || { bad "expected 401 without credentials, got $code"; fails=$((fails + 1)); }
  code=$(curl -s -o /dev/null -w '%{http_code}' -u "${user}:${pw}" "http://127.0.0.1:${port}/" || true)
  [ "$code" = 200 ] && ok "login works (200)" || { bad "login returned $code"; fails=$((fails + 1)); }
  if curl -s "http://127.0.0.1:${port}/healthz" | grep -q '"data":true'; then
    ok "portfolio data present"
  else
    warn "no computed data yet (import exports or wait for the startup rebuild)"
  fi
  return $fails
}

# ------------------------------------------------------------------ deploy
cmd_deploy() {
  local inst; inst=$(instance "${1:-}")
  local ref=${2:-origin/${BRANCH[$inst]}}
  local dir=${DIR[$inst]}
  banner "DEPLOY ${inst^^} → ${ref}"

  section "Preflight"
  [ -d "$dir/.git" ] || die "Not initialised: run init $inst"
  [ -f "$dir/.env" ] || die "Missing $dir/.env"
  [ "$(env_get "$inst" APP_PASSWORD)" != "change-me" ] && [ -n "$(env_get "$inst" APP_PASSWORD)" ] || die "APP_PASSWORD is unset or default"
  [ -w "${DATA[$inst]}" ] || die "Data dir not writable: ${DATA[$inst]}"
  docker info >/dev/null 2>&1 || die "Docker is not reachable"
  local used; used=$(df "${DATA[$inst]}" | awk 'NR==2 {print $5}' | tr -d '%')
  [ "$used" -lt 90 ] || die "Disk ${used}% full"
  ok "checks passed (disk ${used}%)"
  if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]; then
    [ "$inst" = prod ] && die "Uncommitted changes in $dir"
    warn "uncommitted changes in dev checkout are kept (live reload uses them)"
  fi

  section "Backup"
  if [ -n "$(ls -A "${DATA[$inst]}" 2>/dev/null)" ]; then cmd_backup "$inst"; else warn "data dir empty, nothing to back up"; fi

  section "Source"
  local prev; prev=$(git -C "$dir" rev-parse HEAD)
  local prev_branch; prev_branch=$(git -C "$dir" symbolic-ref --short -q HEAD || true)
  git -C "$dir" fetch -q origin
  if [ "$ref" = "origin/${BRANCH[$inst]}" ]; then
    git -C "$dir" checkout -q "${BRANCH[$inst]}"
    git -C "$dir" merge -q --ff-only "origin/${BRANCH[$inst]}"
  else
    git -C "$dir" checkout -q --detach "$ref"
  fi
  local sha; sha=$(git -C "$dir" rev-parse --short HEAD)
  ok "$(git -C "$dir" log -1 --format='%h %s' | cut -c1-72)"
  [ "$prev" = "$(git -C "$dir" rev-parse HEAD)" ] && warn "same commit as before (rebuilding anyway)"

  section "Build & start"
  export TAG="${inst}-${sha}"
  compose "$inst" build -q
  compose "$inst" up -d --remove-orphans
  ok "image portfolio-terminal:${TAG}"

  section "Verify"
  if wait_healthy "$inst" && verify "$inst"; then
    ok "healthy"
    docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^portfolio-terminal:${inst}-" | grep -v ":${TAG}$" \
      | tail -n +3 | xargs -r docker rmi -f >/dev/null 2>&1 || true
    banner "DONE  ${inst^^} ${sha}  http://10.10.20.3:${PORT[$inst]}"
    return 0
  fi

  section "Rollback"
  bad "verification failed; restoring $(git -C "$dir" rev-parse --short "$prev")"
  compose "$inst" logs --tail 40 || true
  if [ -n "$prev_branch" ]; then git -C "$dir" checkout -q -B "$prev_branch" "$prev"; else git -C "$dir" checkout -q --detach "$prev"; fi
  export TAG="${inst}-$(git -C "$dir" rev-parse --short HEAD)"
  compose "$inst" build -q && compose "$inst" up -d
  if wait_healthy "$inst" && verify "$inst"; then
    warn "rolled back to previous commit; investigate before redeploying"
  else
    bad "rollback also failed; restore data with: tar xzf <backup> -C ${DATA[$inst]}"
  fi
  exit 1
}

# ------------------------------------------------------------------ seed-dev
cmd_seed_dev() {
  banner "SEED DEV FROM PROD DATA"
  [ -d "${DATA[prod]}/exports" ] || die "Prod has no data yet"
  [ -d "${DIR[dev]}/.git" ] || die "Dev not initialised: run init dev"
  section "Backup dev"
  if [ -n "$(ls -A "${DATA[dev]}" 2>/dev/null)" ]; then cmd_backup dev; fi
  section "Copy"
  compose dev stop >/dev/null 2>&1 || true
  rsync -a --delete --exclude exports/staging --exclude market/fetch_progress.json "${DATA[prod]}/" "${DATA[dev]}/"
  ok "copied $(du -sh "${DATA[dev]}" | cut -f1)"
  compose dev up -d >/dev/null
  wait_healthy dev && ok "dev restarted"
}

# ------------------------------------------------------------------ promote
cmd_promote() {
  banner "PROMOTE DEV → PROD"
  local sha; sha=$(git -C "${DIR[dev]}" rev-parse HEAD)
  [ -z "$(git -C "${DIR[dev]}" status --porcelain --untracked-files=no)" ] || die "Dev has uncommitted changes; commit and push them first"
  git -C "${DIR[dev]}" fetch -q origin
  git -C "${DIR[dev]}" merge-base --is-ancestor origin/main "$sha" || die "main is not an ancestor of dev's commit; merge first"
  git -C "${DIR[dev]}" push -q origin "${sha}:refs/heads/main"
  ok "main → $(git -C "${DIR[dev]}" rev-parse --short "$sha")"
  cmd_deploy prod
}

# ------------------------------------------------------------------ survey
cmd_survey() {
  banner "PORTFOLIO TERMINAL SURVEY  $(date '+%Y-%m-%d %H:%M')"
  for inst in prod dev; do
    section "${inst^^}  ${DIR[$inst]}"
    if [ ! -d "${DIR[$inst]}/.git" ]; then warn "not initialised"; continue; fi
    echo "Commit   : $(git -C "${DIR[$inst]}" log -1 --format='%h %cr %s' | cut -c1-70)"
    local state; state=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$(container "$inst")" 2>/dev/null || echo "not running")
    echo "Container: $(container "$inst")  $state"
    echo "URL      : http://10.10.20.3:${PORT[$inst]}"
    echo "Data     : $(du -sh "${DATA[$inst]}" 2>/dev/null | cut -f1)  ${DATA[$inst]}"
    local last; last=$(ls -1t "${BACKUPS[$inst]}"/*.tgz 2>/dev/null | head -1 || true)
    echo "Backup   : ${last:-none}"
    local fetch; fetch=$(tail -1 "${DATA[$inst]}/market/fetch_log.jsonl" 2>/dev/null | cut -c1-90 || true)
    echo "Fetch    : ${fetch:-never}"
    case "$state" in *healthy*) [[ "$state" == *unhealthy* ]] && bad "unhealthy" || ok "running" ;; *) warn "not healthy" ;; esac
  done
  section "Host"
  df -h / | awk 'NR==2 {print "Disk     : " $5 " used of " $2}'
  echo ""
}

cmd_logs() { local inst; inst=$(instance "${1:-}"); compose "$inst" logs -f --tail 200; }

cmd_self_update() {
  local target; target=$(readlink -f "$0")
  git --git-dir="$REPO" show main:deploy/portfolio-terminal-deploy.sh > "${target}.new"
  bash -n "${target}.new" || { rm -f "${target}.new"; die "new script has syntax errors; kept current version"; }
  chmod 755 "${target}.new" && mv "${target}.new" "$target"
  ok "installed $(git --git-dir="$REPO" log -1 --format=%h main -- deploy/portfolio-terminal-deploy.sh) → $target"
}

case "${1:-}" in
  survey)   cmd_survey ;;
  init)     cmd_init "${2:-}" ;;
  deploy)   cmd_deploy "${2:-}" "${3:-}" ;;
  backup)   cmd_backup "${2:-}" ;;
  seed-dev) cmd_seed_dev ;;
  promote)  cmd_promote ;;
  logs)     cmd_logs "${2:-}" ;;
  self-update) cmd_self_update ;;
  *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
