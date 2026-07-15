#!/usr/bin/env bash
# scripts/rotate-mqtt-creds.sh — rotate the shared Mosquitto service accounts:
# `server` (the Pi server's own credential — .env SPOREPRINT_MQTT_USERNAME/
# PASSWORD, provisioned by setup.sh), sp-3p (the smart-plug account), and the
# scoped tooling accounts sp-cmd / sp-telemetry.
#
# Per-node credentials are created by scripts/add-node-mqtt-user.sh (one per
# node, username = node_id) and rotated by re-running it. This script is for
# the shared accounts only. Safe to run at any time; the Pi reconnects with
# the new password within the MQTT supervisor's 5s backoff window. Rotating
# sp-3p means re-entering the password in each plug's Tasmota MQTT config.
#
# Usage:
#   ./scripts/rotate-mqtt-creds.sh [user1 user2 ...]  # default: all four

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASSWD="$ROOT/config/mosquitto/passwd"
ENV_FILE="$ROOT/server/.env"

targets=("$@")
if [ "${#targets[@]}" -eq 0 ]; then
  targets=(server sp-cmd sp-telemetry sp-3p)
fi

if ! command -v mosquitto_passwd >/dev/null 2>&1; then
  echo "✗ mosquitto_passwd not in PATH. Install: brew install mosquitto (macOS) or apt install mosquitto (Linux)."
  exit 1
fi

touch "$PASSWD"

for user in "${targets[@]}"; do
  pass=$(openssl rand -hex 24)
  # Rotate in the passwd file (overwrites existing entry).
  mosquitto_passwd -b "$PASSWD" "$user" "$pass"

  # Rewrite the matching SPOREPRINT_MQTT_*_PASS env var.
  env_key=""
  case "$user" in
    # The Pi server connects as `server` (setup.sh) — its password lives in
    # SPOREPRINT_MQTT_PASSWORD. The old mapping rotated sp-cmd's password
    # into that key while the username stayed `server`, which bricked the
    # server's broker auth on every rotation.
    server)       env_key="SPOREPRINT_MQTT_PASSWORD" ;;
    sp-cmd)       env_key="SPOREPRINT_MQTT_CMD_PASSWORD" ;;
    sp-telemetry) env_key="SPOREPRINT_MQTT_TELEMETRY_PASSWORD" ;;
    sp-3p)        env_key="SPOREPRINT_MQTT_3P_PASSWORD" ;;
  esac
  if [ -n "$env_key" ]; then
    if [ -f "$ENV_FILE" ] && grep -q "^${env_key}=" "$ENV_FILE"; then
      tmp=$(mktemp)
      grep -v "^${env_key}=" "$ENV_FILE" > "$tmp"
      echo "${env_key}=${pass}" >> "$tmp"
      mv "$tmp" "$ENV_FILE"
    else
      echo "${env_key}=${pass}" >> "$ENV_FILE"
    fi
    chmod 600 "$ENV_FILE"
    echo "✓ rotated $user (env: $env_key)"
  else
    echo "✓ rotated $user (no env var — custom user)"
  fi
done

echo ""
echo "Restart the Pi server to pick up new credentials:"
echo "  sudo systemctl restart sporeprint"
echo "  (or: docker compose restart server)"
