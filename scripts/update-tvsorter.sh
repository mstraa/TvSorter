#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${TVSORTER_APP_DIR:-/opt/tvsorter}"
SERVICE_NAME="${TVSORTER_SERVICE_NAME:-tvsorter}"
BRANCH="${TVSORTER_BRANCH:-main}"

log() {
  printf '[TvSorter Update] %s\n' "$*"
}

die() {
  printf '[TvSorter Update] ERROR: %s\n' "$*" >&2
  exit 1
}

configure_autologin() {
  log "Configuring Proxmox console autologin"

  install -d /etc/systemd/system/console-getty.service.d
  cat >/etc/systemd/system/console-getty.service.d/override.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear --keep-baud console 115200,38400,9600 $TERM
UNIT

  install -d /etc/systemd/system/container-getty@1.service.d
  cat >/etc/systemd/system/container-getty@1.service.d/override.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear --keep-baud tty%I 115200,38400,9600 $TERM
UNIT

  install -d /etc/systemd/system/getty@tty1.service.d
  cat >/etc/systemd/system/getty@tty1.service.d/override.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
UNIT
}

restart_getty_units() {
  systemctl daemon-reload
  for unit in console-getty.service container-getty@1.service getty@tty1.service; do
    if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q "$unit"; then
      systemctl restart "$unit" || true
    fi
  done
}

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  die "Run update as root inside the TvSorter LXC"
fi

command -v git >/dev/null 2>&1 || die "git is not installed"
command -v systemctl >/dev/null 2>&1 || die "systemctl is not available"

[[ -d "$APP_DIR/.git" ]] || die "TvSorter git checkout not found at $APP_DIR"
[[ -x "$APP_DIR/.venv/bin/python" ]] || die "Python virtualenv not found at $APP_DIR/.venv"

current_branch="$(git -C "$APP_DIR" branch --show-current)"
if [[ "$current_branch" != "$BRANCH" ]]; then
  log "Switching from branch $current_branch to $BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
fi

log "Fetching latest $BRANCH from origin"
git -C "$APP_DIR" fetch origin "$BRANCH"

old_rev="$(git -C "$APP_DIR" rev-parse --short HEAD)"
new_rev="$(git -C "$APP_DIR" rev-parse --short "origin/${BRANCH}")"

if [[ "$old_rev" == "$new_rev" ]]; then
  log "Already up to date at $old_rev"
else
  log "Updating $old_rev -> $new_rev"
  git -C "$APP_DIR" reset --hard "origin/${BRANCH}"
fi

log "Updating Python dependencies"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -e "$APP_DIR"

configure_autologin
restart_getty_units

log "Restarting ${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl restart "${SERVICE_NAME}.service"

if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
  log "Done. ${SERVICE_NAME}.service is running at revision $(git -C "$APP_DIR" rev-parse --short HEAD)"
else
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
  die "${SERVICE_NAME}.service did not start cleanly"
fi
