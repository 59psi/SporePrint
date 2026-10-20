#!/usr/bin/env bash
# scripts/provision-node.sh — print (or generate / rotate) the MQTT
# command-signing key shared by the Pi server and every ESP32 node.
#
# Usage:
#   ./scripts/provision-node.sh [--rotate]
#
# install.sh already provisions the key on first run, so the Pi signs every
# command from day one (nodes without the key accept signed commands; a
# cloud-paired Pi would otherwise refuse to send any). Run this to print the
# key for the node portals, or with --rotate to replace it.
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
#   * Rotation = re-run with --rotate, re-key EVERY node, and only then apply
#     the key to the Pi server. Re-key a node in its portal: reopen it with a
#     BOOT 3-10 s hold, then release (camera: short IO13 to GND 3-10 s —
#     there is no button on that pin) → join SporePrint-Setup → paste the new
#     key, leaving the other password fields blank to keep them. No factory
#     reset (a hold longer than 10 s) is needed — that would wipe WiFi, MQTT
#     login and OTA password.
#   * A re-keyed node keeps the key it replaced and accepts commands signed
#     with either one until the first command signed with the new key
#     reaches it, which retires the old key (firmware/lib/sp_core/
#     hmac_verify.h). So the Pi, still signing with the old key while you
#     re-key, reaches every node throughout. Firmware without that grace
#     holds one key and rejects every command between its re-key and the
#     Pi's switch: re-key such nodes last. The new key is in .env as soon as
#     this script has run: the next `docker compose up -d` (or a bare-metal
#     restart) applies it.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_ENV="$ROOT/.env"            # docker compose interpolates this one
SERVER_ENV="$ROOT/server/.env"   # bare-metal: uvicorn runs from server/
ROTATE=0
# shellcheck source=scripts/lib/host.sh
. "$ROOT/scripts/lib/host.sh"

for arg in "$@"; do
  case "$arg" in
    --rotate) ROTATE=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0"   # the header comment
      exit 0
      ;;
  esac
done

read_key() { # read_key FILE — prints the key as compose and the server read it, or nothing.
  sp_env_get "$1" SPOREPRINT_MQTT_HMAC_KEY
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
ROOT_KEY_BEFORE="$(read_key "$ROOT_ENV")"
CURRENT_KEY="$ROOT_KEY_BEFORE"
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

REPLACED=0
if [ -n "$CURRENT_KEY" ] && [ "$KEY" != "$CURRENT_KEY" ]; then
  REPLACED=1
fi
# Which goes first. The Pi only when this run gave the root .env (what
# compose reads) its first key without replacing one: the server signs with
# no key until then, and a node without the key accepts signed frames, so
# nothing is cut off. Otherwise the nodes: a re-keyed node keeps accepting
# the key it replaced until the Pi switches (also when this is a re-run, in
# the middle of a rotation, to print the key again).
PI_FIRST=0
if [ "$REPLACED" -eq 0 ] && [ -z "$ROOT_KEY_BEFORE" ]; then
  PI_FIRST=1
fi

pi_step() { # pi_step N — apply the key to the Pi server
  echo "$1. Apply the key to the Pi server:"
  echo "   Docker:     cd $ROOT && ${DC_PREFIX}docker compose up -d server"
  echo "               (recreates the container — 'restart' would keep the old env)"
  echo "   Bare metal: sudo systemctl restart sporeprint"
}

nodes_step() { # nodes_step N — the key into every node's setup portal
  echo "$1. For EACH ESP32 node, enter the key in the node's captive portal:"
  echo ""
  echo "   New node: power it, join the 'SporePrint-Setup' WiFi AP, open"
  echo "   http://192.168.4.1/, paste the key into 'Command signing key'."
  echo ""
  echo "   Already-provisioned node: reopen its portal — hold BOOT 3-10 s, then"
  echo "   release (camera: short IO13 to GND 3-10 s; there is no button on that"
  echo "   pin). Join 'SporePrint-Setup', paste the key into 'Command signing"
  echo "   key' and leave the other password fields blank to keep them. No"
  echo "   factory reset: holding longer than 10 s wipes WiFi, MQTT and OTA."
}

echo ""
echo "── Next steps ─────────────────────────────────────────────────────"
echo ""
if [ "$REPLACED" -eq 1 ]; then
  echo "⚠ This REPLACED the signing key: re-key every node (step 1) BEFORE you"
  echo "  apply it to the Pi server (step 2). A re-keyed node also accepts the key"
  echo "  it replaced, until the first command signed with the new one reaches it,"
  echo "  so the Pi reaches every node throughout. Firmware without that grace"
  echo "  holds one key and rejects every command between its re-key and step 2:"
  echo "  re-key such nodes last. The key is already in .env, and the next"
  echo "  'docker compose up -d' (or a bare-metal restart) applies it. To print it"
  echo "  again, run this script without --rotate."
  echo ""
fi
if [ "$PI_FIRST" -eq 1 ]; then
  pi_step 1
  echo ""
  nodes_step 2
else
  nodes_step 1
  echo ""
  pi_step 2
  if [ "$REPLACED" -eq 1 ]; then
    echo "   Each node drops the old key at the first command signed with this"
    echo "   one; a node the Pi seldom commands keeps it until then. An empty"
    echo "   command retires it at once (docs/firmware-security.md, Rotating the"
    echo "   key)."
  fi
fi
echo ""
echo "3. A node with NO key accepts every command and logs a WARNING each time:"
echo "      [SEC] hmac_key not provisioned — accepting unsigned cmd/..."
echo "   A node with a DIFFERENT key rejects every command until it has this one:"
echo "      [SEC] Rejecting cmd/...: signature mismatch"
echo "   A re-keyed node says which key verified each command until the old key"
echo "   is retired:"
echo "      [SEC] cmd/... verified with the PREVIOUS signing key - ..."
echo "      [SEC] cmd/... verified with the new signing key - previous key retired"
echo ""
echo "4. Verify by sending a test command from the Pi and watching Serial:"
echo "   A signed frame logs:       [CH] fae: ON pwm=200"
echo "   A bad signature logs:      [SEC] Rejecting cmd/...: signature mismatch"
echo ""
echo "Key: $KEY"
echo ""
