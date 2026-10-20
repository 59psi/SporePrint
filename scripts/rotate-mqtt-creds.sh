#!/usr/bin/env bash
# scripts/rotate-mqtt-creds.sh — rotate the shared Mosquitto service accounts:
# `server` (the Pi server's own credential — .env SPOREPRINT_MQTT_USERNAME/
# PASSWORD, provisioned by install.sh), the scoped tooling accounts sp-cmd /
# sp-telemetry, and, only when named, sp-3p (the smart-plug account).
#
# Per-node credentials are created by scripts/add-node-mqtt-user.sh (one per
# node, username = node_id) and rotated by re-running it. This script is for
# the shared accounts only.
#
# sp-3p is rotated only when named (`./scripts/rotate-mqtt-creds.sh sp-3p`):
# the broker reload drops every plug still holding the old password, and each
# stays off the broker, its relay held in whatever state it was in, until the
# new password is typed into that plug's Tasmota/Shelly MQTT settings. The
# script prints it.
#
# Where the new passwords go, in this order:
#   * config/mosquitto/passwd — edited in place inside a throwaway broker
#     container (scripts/lib/broker.sh), so per-node users are kept. If that
#     edit fails, nothing else is changed.
#   * the repo-root .env — the file docker compose interpolates into the
#     server + broker-healthcheck environment. server/.env (bare-metal /
#     systemd installs, where uvicorn runs from server/) gets the `server`
#     password too when it exists, so the two never diverge — and nothing
#     else: the server uses no other of these passwords.
# Then the broker is reloaded and, when the compose stack is running, the
# server + mqtt containers are recreated (`docker compose up -d` — a plain
# `restart` would keep the OLD password from the old environment and lock
# the Pi out of its own broker).
#
# Usage:
#   ./scripts/rotate-mqtt-creds.sh [user1 user2 ...]
#       default: server sp-cmd sp-telemetry (name sp-3p to rotate the plugs' login)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASSWD="$ROOT/config/mosquitto/passwd"
# shellcheck source=scripts/lib/broker.sh
. "$ROOT/scripts/lib/broker.sh"
# shellcheck source=scripts/lib/host.sh
. "$ROOT/scripts/lib/host.sh"

if [ "$#" -gt 0 ]; then
  targets=("$@")
else
  # Not sp-3p: rotating it takes every smart plug off the broker until the
  # new password is typed into each one, so it happens only when named.
  targets=(server sp-cmd sp-telemetry)
fi

# .env files to update: the root .env (compose; always — it is also where the
# operator finds the sp-3p password for the plugs), plus server/.env if present.
# server/.env is the bare-metal server's own dotenv: only the password the
# server itself uses (SPOREPRINT_MQTT_PASSWORD) is mirrored there, so the plug
# and tooling passwords are not copied into a file the server never needs
# them in.
ENV_FILES=("$ROOT/.env")
[ -f "$ROOT/server/.env" ] && ENV_FILES+=("$ROOT/server/.env")
SERVER_READS="SPOREPRINT_MQTT_PASSWORD"

if [ -d "$PASSWD" ]; then
  echo "✗ $PASSWD is a directory (Docker created it). Re-run ./install.sh first."
  exit 1
fi

USE_DOCKER=0
if sp_docker_init; then
  USE_DOCKER=1
elif ! command -v mosquitto_passwd >/dev/null 2>&1 || { [ -e "$PASSWD" ] && [ ! -w "$PASSWD" ]; }; then
  echo "✗ Cannot edit $PASSWD: need a reachable docker daemon (the file belongs to"
  echo "  the broker's uid ${SP_BROKER_UID} on Linux), or mosquitto_passwd with write access."
  exit 1
fi

# 1. A new password for every target, into the broker's password file first.
#    The .env files are rewritten only once that succeeded: written the other
#    way round, a failed passwd edit left .env holding passwords the broker
#    did not know, and the next server start was refused by its own broker.
passwords=()
pairs=""
for user in "${targets[@]}"; do
  pass=$(openssl rand -hex 24)
  passwords+=("$pass")
  pairs+="${user}"$'\n'"${pass}"$'\n'
done

# A failed edit ends the script here (set -e), before any .env is touched.
passwd_failed() {
  echo "✗ Could not update $PASSWD, so no .env file was changed. If the edit stopped" >&2
  echo "  part-way, some of these accounts may already have a new password there:" >&2
  echo "  re-run this script (it sets fresh passwords in both) before the broker is" >&2
  echo "  reloaded or restarted." >&2
}
trap passwd_failed EXIT
if [ "$USE_DOCKER" = "1" ]; then
  printf '%s' "$pairs" | sp_passwd_update "$ROOT"
else
  for i in "${!targets[@]}"; do
    sp_host_passwd_set "$PASSWD" "${targets[$i]}" "${passwords[$i]}"
  done
fi
trap - EXIT

# 2. The matching SPOREPRINT_MQTT_*_PASSWORD env vars.
server_rotated=0
plug_pass=""
for i in "${!targets[@]}"; do
  user="${targets[$i]}"
  pass="${passwords[$i]}"
  env_key=""
  case "$user" in
    # The Pi server connects as `server` — its password lives in
    # SPOREPRINT_MQTT_PASSWORD. (An old mapping rotated sp-cmd's password
    # into that key while the username stayed `server`, which bricked the
    # server's broker auth on every rotation.)
    server)       env_key="SPOREPRINT_MQTT_PASSWORD"; server_rotated=1 ;;
    sp-cmd)       env_key="SPOREPRINT_MQTT_CMD_PASSWORD" ;;
    sp-telemetry) env_key="SPOREPRINT_MQTT_TELEMETRY_PASSWORD" ;;
    sp-3p)        env_key="SPOREPRINT_MQTT_3P_PASSWORD"; plug_pass="$pass" ;;
  esac
  if [ -n "$env_key" ]; then
    written=()
    for f in "${ENV_FILES[@]}"; do
      if [ "$f" = "$ROOT/server/.env" ] && [ "$env_key" != "$SERVER_READS" ]; then
        continue
      fi
      sp_env_set "$f" "$env_key" "$pass"
      written+=("$f")
    done
    echo "✓ rotated $user (env: $env_key → ${written[*]})"
  else
    echo "✓ rotated $user (no env var — custom user; password: $pass)"
  fi
done

sp_broker_reload "$ROOT"

if [ -n "$plug_pass" ]; then
  echo ""
  echo "⚠ Smart plugs: once the broker has reloaded, every plug still using the old"
  echo "  sp-3p password is off the broker and stays off, its relay held in whatever"
  echo "  state it was in and out of the server's reach, until you enter the new"
  echo "  password in that plug (Tasmota: Configuration → MQTT → Password; Shelly:"
  echo "  Settings → MQTT → Password). The new sp-3p password:"
  echo "    $plug_pass"
  echo "  (also SPOREPRINT_MQTT_3P_PASSWORD in $ROOT/.env)"
fi

DC_PREFIX=""; [ "$SP_DOCKER_MODE" = "sudo" ] && DC_PREFIX="sudo "
if [ "$server_rotated" = "1" ]; then
  if sp_broker_running "$ROOT"; then
    # Recreate (not restart) so the containers pick up the new .env value.
    sp_docker compose -f "$ROOT/docker-compose.yml" up -d server mqtt
    echo "✓ server + mqtt recreated with the new 'server' password"
  else
    echo ""
    echo "Apply the new 'server' password to the Pi server:"
    echo "  Docker:     cd $ROOT && ${DC_PREFIX}docker compose up -d   (not 'restart' — it keeps the old env)"
    echo "  Bare metal: sudo systemctl restart sporeprint"
  fi
fi
