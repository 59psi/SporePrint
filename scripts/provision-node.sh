#!/usr/bin/env bash
# scripts/provision-node.sh — generate + deploy the MQTT HMAC key that
# closes Sentinel finding C-1 (firmware MQTT commands bypass HMAC signing).
#
# Usage:
#   ./scripts/provision-node.sh [--rotate]
#
# What this does:
#   1. Generates a 64-char (256-bit) hex key, or reuses the existing one
#      from server/.env unless --rotate is passed.
#   2. Writes it to server/.env as SPOREPRINT_MQTT_HMAC_KEY.
#   3. Prints flashing instructions for each ESP32 node. The key must be
#      written into NVS under the `hmac_key` namespace before the node
#      starts enforcing signed commands.
#
# Why this is a separate script from setup.sh:
#   * Key rotation is an operational event, not a one-time setup.
#   * The firmware migration path (warn + accept when unprovisioned) means
#     the Pi can enable signing before every node has the key, with a
#     visible Serial warning driving the operator toward provisioning.
#   * Keeping it out of setup.sh makes the upgrade path explicit for
#     existing v3.4.8 deployments.
#
# Security notes:
#   * The key is the master secret for firmware command authenticity. Treat
#     like an SSH private key — chmod 600 on server/.env, never commit.
#   * A compromise of this key = attacker-controlled commands for every
#     node paired with the Pi. Rotate on any suspicion of broker leak.
#   * Future work: per-node keys instead of shared key; auto-rotation on
#     cloud pair.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/server/.env"
ROTATE=0

for arg in "$@"; do
  case "$arg" in
    --rotate) ROTATE=1 ;;
    -h|--help)
      sed -n '2,31p' "$0"
      exit 0
      ;;
  esac
done

# Load current key if present
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
    # Replace in place
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
echo "1. Restart the Pi server so the new key takes effect:"
echo "   sudo systemctl restart sporeprint     # or docker compose restart server"
echo ""
echo "2. For EACH ESP32 node in your stack (relay, climate, lighting, cam),"
echo "   bake the key into its NVS by re-flashing with the build flag:"
echo ""
echo "      cd firmware"
echo "      SPOREPRINT_PROVISION_HMAC=$KEY pio run -e relay_node -t upload"
echo "      SPOREPRINT_PROVISION_HMAC=$KEY pio run -e climate_node -t upload"
echo "      SPOREPRINT_PROVISION_HMAC=$KEY pio run -e lighting_node -t upload"
echo "      SPOREPRINT_PROVISION_HMAC=$KEY pio run -e cam_node -t upload"
echo ""
echo "   The firmware checks the build-flag on boot: if NVS has no"
echo "   hmac_key AND the build flag is set, it writes the flag value into"
echo "   NVS. Subsequent boots read from NVS normally — safe to re-flash"
echo "   without the flag after first boot."
echo ""
echo "   On first successful store you will see on Serial:"
echo "      [CFG] hmac_key stored from build flag (64 chars)"
echo ""
echo "   v3.5.0 will add a Pi-mediated provisioning flow so re-flashing"
echo "   is not required for key rotation. Until then, rotation means"
echo "   re-running this script with --rotate + re-flashing every node."
echo ""
echo "3. Until every node has the key, nodes without it will log a WARNING"
echo "   on every accepted unsigned command:"
echo "      [SEC] WARNING: hmac_key not provisioned — accepting unsigned command"
echo ""
echo "4. Verify by sending a test command from the Pi and watching Serial:"
echo "   A signed frame logs:       [RELAY] Ch0 (fae): ON PWM=200"
echo "   A bad signature logs:      [SEC] Rejecting command on ... signature mismatch"
echo ""
echo "Key: $KEY"
echo ""
