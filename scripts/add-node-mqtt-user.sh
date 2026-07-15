#!/usr/bin/env bash
# scripts/add-node-mqtt-user.sh — create the broker credential for ONE node.
#
# Usage:
#   ./scripts/add-node-mqtt-user.sh <node_id>          # e.g. climate-01
#
# Why this exists: the broker refuses anonymous clients
# (config/mosquitto/mosquitto.conf: allow_anonymous false), and the ACL's
# per-node pattern section scopes each node to sporeprint/<its-username>/…
# — so every ESP32 node needs a broker user WHOSE NAME IS ITS node_id.
# Nothing else creates these: setup.sh provisions only the `server` and
# `sp-3p` accounts, and the captive portal only STORES what you type into
# it. Run this once per node, before provisioning the node.
#
# What it does:
#   1. Generates a password and writes <node_id> into config/mosquitto/passwd
#      (mosquitto_passwd locally, or via the eclipse-mosquitto docker image).
#   2. Reloads the broker so the credential is live.
#   3. Prints exactly what to enter in the node's SporePrint-Setup portal.
#
# The username MUST equal the node_id — the ACL patterns expand %u to scope
# the node to its own topics. A relay-01 credential cannot write climate-01's
# telemetry, which is the point.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASSWD="$ROOT/config/mosquitto/passwd"

NODE_ID="${1:-}"
if [ -z "$NODE_ID" ]; then
  echo "Usage: $0 <node_id>   (e.g. climate-01, relay-01, lighting-01, cam-01)"
  exit 1
fi
if ! [[ "$NODE_ID" =~ ^[a-zA-Z0-9_-]{1,32}$ ]]; then
  echo "✗ node_id must be alphanumeric/_/- (max 32 chars) — it doubles as the MQTT username and topic segment."
  exit 1
fi

PASS=$(openssl rand -hex 16)
touch "$PASSWD"

if command -v mosquitto_passwd >/dev/null 2>&1; then
  mosquitto_passwd -b "$PASSWD" "$NODE_ID" "$PASS"
elif command -v docker >/dev/null 2>&1; then
  docker run --rm -v "$ROOT/config/mosquitto:/work" eclipse-mosquitto:2 \
    mosquitto_passwd -b /work/passwd "$NODE_ID" "$PASS"
else
  echo "✗ Need mosquitto_passwd or docker. Install: apt install mosquitto (Linux) / brew install mosquitto (macOS)."
  exit 1
fi
chmod 600 "$PASSWD"

# Reload the broker so the new credential is live (SIGHUP re-reads passwd/acl).
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -q mosquitto; then
  docker kill --signal=HUP "$(docker ps --format '{{.Names}}' | grep mosquitto | head -1)" >/dev/null
  echo "✓ broker reloaded"
else
  echo "⚠ Reload the broker to activate the credential: docker compose kill -s HUP mosquitto"
fi

echo ""
echo "✓ Broker user '$NODE_ID' created."
echo ""
echo "In the node's SporePrint-Setup portal, enter:"
echo "  Node ID:        $NODE_ID"
echo "  MQTT username:  $NODE_ID"
echo "  MQTT password:  $PASS"
echo ""
echo "(The username must equal the Node ID — the broker ACL scopes the node"
echo " to its own topics by username.)"
