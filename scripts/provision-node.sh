#!/usr/bin/env bash
# scripts/provision-node.sh — generate (or reuse) the MQTT command-signing
# key shared by the Pi server and every ESP32 node.
#
# Usage:
#   ./scripts/provision-node.sh [--rotate]
#
# What this does:
#   1. Reuses the existing SPOREPRINT_MQTT_HMAC_KEY (repo-root .env first,
#      then server/.env) unless --rotate is passed; otherwise generates a
#      64-char (256-bit) hex key.
#   2. Writes it to the repo-root .env — the file docker compose reads — and
#      to server/.env too when that exists (bare-metal / systemd installs,
#      where uvicorn runs from server/), so the two never diverge.
#   3. Prints the node-side provisioning steps.
#
# v2 firmware: nodes take the key through the CAPTIVE PORTAL ("Command
# signing key" field). An empty field means warn-and-accept mode (the node
# logs a warning on every unsigned command it honours).
#
# Security notes:
#   * The key is the master secret for firmware command authenticity. Treat
#     like an SSH private key — the .env files are chmod 600, never commit.
#   * A compromise of this key = attacker-controlled commands for every
#     node paired with the Pi. Rotate on any suspicion of broker leak.
#   * Rotation = re-run with --rotate, apply it to the Pi server, then update
#     each node via its portal (factory-reset hold 10 s → rejoin
#     SporePrint-Setup → paste the new key) or re-provision in place.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_ENV="$ROOT/.env"            # docker compose interpolates this one
SERVER_ENV="$ROOT/server/.env"   # bare-metal: uvicorn runs from server/
ROTATE=0

for arg in "$@"; do
  case "$arg" in
    --rotate) ROTATE=1 ;;
    -h|--help)
      sed -n '2,29p' "$0"
      exit 0
      ;;
  esac
done

read_key() { # read_key FILE — prints the key, or nothing.
  [ -f "$1" ] || return 0
  grep '^SPOREPRINT_MQTT_HMAC_KEY=' "$1" | tail -1 | cut -d= -f2- || true
}

write_key() { # write_key FILE KEY — replace in place or append; chmod 600.
  local file="$1" key="$2" tmp
  tmp="$(mktemp)"
  if [ -f "$file" ]; then
    grep -v '^SPOREPRINT_MQTT_HMAC_KEY=' "$file" > "$tmp" || true
  fi
  printf 'SPOREPRINT_MQTT_HMAC_KEY=%s\n' "$key" >> "$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
}

# Root first: that is what the dockerized server receives. Fall back to a
# key an older version of this script left in server/.env — nodes may
# already hold it, so a fresh key here would make them reject every frame.
CURRENT_KEY="$(read_key "$ROOT_ENV")"
[ -n "$CURRENT_KEY" ] || CURRENT_KEY="$(read_key "$SERVER_ENV")"

if [ -n "$CURRENT_KEY" ] && [ "$ROTATE" -ne 1 ]; then
  KEY="$CURRENT_KEY"
  echo "✓ Reusing existing SPOREPRINT_MQTT_HMAC_KEY"
  echo "  (pass --rotate to generate a fresh key)"
else
  KEY=$(openssl rand -hex 32)
  echo "✓ Generated new 64-char hex key"
fi

TARGETS=("$ROOT_ENV")
[ -f "$SERVER_ENV" ] && TARGETS+=("$SERVER_ENV")
for f in "${TARGETS[@]}"; do
  if [ "$(read_key "$f")" != "$KEY" ]; then
    write_key "$f" "$KEY"
    echo "  Wrote to $f (chmod 600)"
  fi
done

DC_PREFIX=""
if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
  DC_PREFIX="sudo "
fi

echo ""
echo "── Next steps ─────────────────────────────────────────────────────"
echo ""
echo "1. Apply the key to the Pi server:"
echo "   Docker:     cd $ROOT && ${DC_PREFIX}docker compose up -d server"
echo "               (recreates the container — 'restart' would keep the old env)"
echo "   Bare metal: sudo systemctl restart sporeprint"
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
