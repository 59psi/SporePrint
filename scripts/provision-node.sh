#!/usr/bin/env bash
# scripts/provision-node.sh — generate (or reuse) the MQTT command-signing
# key shared by the Pi server and every ESP32 node.
#
# Usage:
#   ./scripts/provision-node.sh [--rotate]
#
# What this does:
#   1. Generates a 64-char (256-bit) hex key, or reuses the existing one
#      from server/.env unless --rotate is passed.
#   2. Writes it to server/.env as SPOREPRINT_MQTT_HMAC_KEY.
#   3. Prints the node-side provisioning steps.
#
# v2 firmware note: nodes take the key through the CAPTIVE PORTAL
# ("Command signing key" field) — there is no build-flag path anymore.
# The v1 flow (SPOREPRINT_PROVISION_HMAC=<key> pio run …) baked the key in
# at compile time through a preprocessor path that corrupted it; v2 stores
# what you type, verifies against the shared golden vectors, and an empty
# field means warn-and-accept mode (the node logs a warning on every
# unsigned command it honours).
#
# Security notes:
#   * The key is the master secret for firmware command authenticity. Treat
#     like an SSH private key — chmod 600 on server/.env, never commit.
#   * A compromise of this key = attacker-controlled commands for every
#     node paired with the Pi. Rotate on any suspicion of broker leak.
#   * Rotation = re-run with --rotate, restart the Pi server, then update
#     each node via its portal (factory-reset hold 10 s → rejoin
#     SporePrint-Setup → paste the new key) or re-provision in place.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/server/.env"
ROTATE=0

for arg in "$@"; do
  case "$arg" in
    --rotate) ROTATE=1 ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
  esac
done

CURRENT_KEY=""
if [ -f "$ENV_FILE" ] && grep -q '^SPOREPRINT_MQTT_HMAC_KEY=' "$ENV_FILE"; then
  CURRENT_KEY=$(grep '^SPOREPRINT_MQTT_HMAC_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)
fi

if [ -n "$CURRENT_KEY" ] && [ "$ROTATE" -ne 1 ]; then
  KEY="$CURRENT_KEY"
  echo "✓ Reusing existing SPOREPRINT_MQTT_HMAC_KEY from $ENV_FILE"
  echo "  (pass --rotate to generate a fresh key)"
else
  KEY=$(openssl rand -hex 32)
  echo "✓ Generated new 64-char hex key"
  if [ ! -f "$ENV_FILE" ]; then
    echo "  Creating $ENV_FILE"
    touch "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
  if grep -q '^SPOREPRINT_MQTT_HMAC_KEY=' "$ENV_FILE"; then
    tmp=$(mktemp)
    grep -v '^SPOREPRINT_MQTT_HMAC_KEY=' "$ENV_FILE" > "$tmp"
    echo "SPOREPRINT_MQTT_HMAC_KEY=$KEY" >> "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    echo "SPOREPRINT_MQTT_HMAC_KEY=$KEY" >> "$ENV_FILE"
  fi
  chmod 600 "$ENV_FILE"
  echo "  Wrote to $ENV_FILE (chmod 600)"
fi

echo ""
echo "── Next steps ─────────────────────────────────────────────────────"
echo ""
echo "1. Restart the Pi server so the key takes effect:"
echo "   sudo systemctl restart sporeprint     # or docker compose restart server"
echo ""
echo "2. For EACH ESP32 node, enter the key in the node's captive portal:"
echo ""
echo "   New node: power it, join the 'SporePrint-Setup' WiFi AP, open"
echo "   http://192.168.4.1/, paste the key into 'Command signing key'."
echo ""
echo "   Already-provisioned node: hold the factory-reset button 10 s"
echo "   (BOOT on dev boards, GPIO 13 on the cam), then provision via the"
echo "   portal as above. WiFi + broker settings re-enter with it."
echo ""
echo "3. Until a node has the key, it logs a WARNING on every accepted"
echo "   unsigned command:"
echo "      [SEC] hmac_key not provisioned — accepting unsigned cmd/..."
echo ""
echo "4. Verify by sending a test command from the Pi and watching Serial:"
echo "   A signed frame logs:       [CH] fae: ON pwm=200"
echo "   A bad signature logs:      [SEC] Rejecting cmd/...: signature mismatch"
echo ""
echo "Key: $KEY"
echo ""
