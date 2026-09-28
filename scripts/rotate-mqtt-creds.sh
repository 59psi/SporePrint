#!/usr/bin/env bash
# scripts/rotate-mqtt-creds.sh — rotate the shared Mosquitto service accounts:
# `server` (the Pi server's own credential — .env SPOREPRINT_MQTT_USERNAME/
# PASSWORD, provisioned by install.sh), sp-3p (the smart-plug account), and
# the scoped tooling accounts sp-cmd / sp-telemetry.
#
# Per-node credentials are created by scripts/add-node-mqtt-user.sh (one per
# node, username = node_id) and rotated by re-running it. This script is for
# the shared accounts only. Rotating sp-3p means re-entering the password in
# each plug's Tasmota/Shelly MQTT config.
#
# Where the new passwords go:
#   * config/mosquitto/passwd — edited in place inside a throwaway broker
#     container (scripts/lib/broker.sh), so per-node users are kept.
#   * the repo-root .env — the file docker compose interpolates into the
#     server + broker-healthcheck environment. server/.env (bare-metal /
#     systemd installs, where uvicorn runs from server/) gets the `server`
#     password too when it exists, so the two never diverge — and nothing
#     else: the server refuses to start on a key it does not know.
# Then the broker is reloaded and, when the compose stack is running, the
# server + mqtt containers are recreated (`docker compose up -d` — a plain
# `restart` would keep the OLD password from the old environment and lock
# the Pi out of its own broker).
#
# Usage:
#   ./scripts/rotate-mqtt-creds.sh [user1 user2 ...]  # default: all four

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASSWD="$ROOT/config/mosquitto/passwd"
# shellcheck source=scripts/lib/broker.sh
. "$ROOT/scripts/lib/broker.sh"

if [ "$#" -gt 0 ]; then
  targets=("$@")
else
  targets=(server sp-cmd sp-telemetry sp-3p)
fi

# .env files to update: the root .env (compose; always — it is also where the
# operator finds the sp-3p password for the plugs), plus server/.env if present.
# server/.env is the bare-metal server's own dotenv, and the server refuses to
# start on a non-empty key it does not know — so only the password the
# server itself uses (SPOREPRINT_MQTT_PASSWORD) is mirrored there.
ENV_FILES=("$ROOT/.env")
[ -f "$ROOT/server/.env" ] && ENV_FILES+=("$ROOT/server/.env")
SERVER_READS="SPOREPRINT_MQTT_PASSWORD"

env_set() { # env_set FILE KEY VALUE — replace in place or append; keeps 0600.
  local file="$1" key="$2" val="$3" tmp
  tmp="$(mktemp)"
  if [ -f "$file" ] && grep -q "^${key}=" "$file"; then
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' "$file" > "$tmp"
  else
    { [ -f "$file" ] && cat "$file"; printf '%s=%s\n' "$key" "$val"; } > "$tmp"
  fi
  mv "$tmp" "$file"
  chmod 600 "$file"
}

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

pairs=""
server_rotated=0
for user in "${targets[@]}"; do
  pass=$(openssl rand -hex 24)
  if [ "$USE_DOCKER" = "1" ]; then
    pairs+="${user}"$'\n'"${pass}"$'\n'
  else
    [ -f "$PASSWD" ] || : > "$PASSWD"
    mosquitto_passwd -b "$PASSWD" "$user" "$pass"
    chmod 600 "$PASSWD"
  fi

  # Rewrite the matching SPOREPRINT_MQTT_*_PASSWORD env var.
  env_key=""
  case "$user" in
    # The Pi server connects as `server` — its password lives in
    # SPOREPRINT_MQTT_PASSWORD. (An old mapping rotated sp-cmd's password
    # into that key while the username stayed `server`, which bricked the
    # server's broker auth on every rotation.)
    server)       env_key="SPOREPRINT_MQTT_PASSWORD"; server_rotated=1 ;;
    sp-cmd)       env_key="SPOREPRINT_MQTT_CMD_PASSWORD" ;;
    sp-telemetry) env_key="SPOREPRINT_MQTT_TELEMETRY_PASSWORD" ;;
    sp-3p)        env_key="SPOREPRINT_MQTT_3P_PASSWORD" ;;
  esac
  if [ -n "$env_key" ]; then
    written=()
    for f in "${ENV_FILES[@]}"; do
      if [ "$f" = "$ROOT/server/.env" ] && [ "$env_key" != "$SERVER_READS" ]; then
        continue
      fi
      env_set "$f" "$env_key" "$pass"
      written+=("$f")
    done
    echo "✓ rotated $user (env: $env_key → ${written[*]})"
  else
    echo "✓ rotated $user (no env var — custom user; password: $pass)"
  fi
done

if [ "$USE_DOCKER" = "1" ]; then
  printf '%s' "$pairs" | sp_passwd_update "$ROOT"
fi

sp_broker_reload "$ROOT"

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
