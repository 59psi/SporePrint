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
# Nothing else creates these: install.sh provisions only the `server` and
# `sp-3p` accounts, and the captive portal only STORES what you type into
# it. Run this once per node, before provisioning the node. Re-running it
# for the same node_id rotates that node's password.
#
# What it does:
#   1. Generates a password and writes <node_id> into config/mosquitto/passwd
#      — in place, inside a throwaway container of the broker image (see
#      scripts/lib/broker.sh for why), so other users are kept.
#   2. Reloads the compose broker (`docker compose kill -s HUP mqtt`) so the
#      credential is live.
#   3. Prints exactly what to enter in the node's SporePrint-Setup portal.
#
# The username MUST equal the node_id — the ACL patterns expand %u to scope
# the node to its own topics. A relay-01 credential cannot write climate-01's
# telemetry, which is the point.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASSWD="$ROOT/config/mosquitto/passwd"
# shellcheck source=scripts/lib/broker.sh
. "$ROOT/scripts/lib/broker.sh"

NODE_ID="${1:-}"
if [ -z "$NODE_ID" ]; then
  echo "Usage: $0 <node_id>   (e.g. climate-01, relay-01, lighting-01, cam-01)"
  exit 1
fi
if ! [[ "$NODE_ID" =~ ^[a-zA-Z0-9_-]{1,32}$ ]]; then
  echo "✗ node_id must be alphanumeric/_/- (max 32 chars) — it doubles as the MQTT username and topic segment."
  exit 1
fi
if [ -d "$PASSWD" ]; then
  echo "✗ $PASSWD is a directory (Docker created it when the stack was started"
  echo "  before install.sh). Re-run ./install.sh — it repairs this — then retry."
  exit 1
fi

PASS=$(openssl rand -hex 16)

if sp_docker_init; then
  printf '%s\n%s\n' "$NODE_ID" "$PASS" | sp_passwd_update "$ROOT"
elif command -v mosquitto_passwd >/dev/null 2>&1 && { [ ! -e "$PASSWD" ] || [ -w "$PASSWD" ]; }; then
  # No docker here (e.g. a bare-metal dev broker): edit with the host tool.
  [ -f "$PASSWD" ] || : > "$PASSWD"
  mosquitto_passwd -b "$PASSWD" "$NODE_ID" "$PASS"
  chmod 600 "$PASSWD"
else
  echo "✗ Cannot edit $PASSWD: need a reachable docker daemon (the file belongs to"
  echo "  the broker's uid ${SP_BROKER_UID} on Linux), or mosquitto_passwd with write access."
  echo "  Install: apt install mosquitto-clients (Linux) / brew install mosquitto (macOS)."
  exit 1
fi

# Reload the broker so the new credential is live (SIGHUP re-reads passwd/acl).
sp_broker_reload "$ROOT"

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
