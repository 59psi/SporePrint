#!/usr/bin/env bash
# scripts/add-plug-mqtt-user.sh — give ONE smart plug a broker login of its own.
#
# Usage:
#   ./scripts/add-plug-mqtt-user.sh <name>          # e.g. heater
#
# <name> is the plug's single topic level, which also makes its plug id
# (plug-<name>, what the built-in rules drive):
#   Tasmota       its Topic (Full Topic tasmota/%topic%/%prefix%/)
#   Shelly Gen2+  the role in its MQTT prefix shellies/<name>
#   Shelly Gen1   its device id (shellies/<device id>/...)
#
# Why: the shared sp-3p login lives in every plug, and a plug's web page
# usually has no password, so anyone who reads it there can switch every
# plug and fake their states. The ACL scopes a per-plug login to its own
# tree (config/mosquitto/acl.conf: pattern readwrite tasmota/%u/# and
# shellies/%u/#), so one plug's password reaches that plug only.
#
# What it does:
#   1. Writes <name> with a new password into config/mosquitto/passwd, in
#      place, inside a throwaway broker container (scripts/lib/broker.sh).
#   2. Lists <name> in SPOREPRINT_MQTT_PLUG_USERS (.env, and server/.env when
#      it exists) and recreates the server: the ACL's per-node patterns let
#      every login post under sporeprint/<its name>/, and the server drops
#      those frames for the names listed there instead of taking a node.
#   3. Reloads the broker and prints what to enter in the plug.
# Re-running it for the same name gives that plug a new password.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASSWD="$ROOT/config/mosquitto/passwd"
# shellcheck source=scripts/lib/broker.sh
. "$ROOT/scripts/lib/broker.sh"
# shellcheck source=scripts/lib/host.sh
. "$ROOT/scripts/lib/host.sh"

NAME="${1:-}"
if [ -z "$NAME" ]; then
  echo "Usage: $0 <name>   (the plug's Tasmota Topic or Shelly role, e.g. heater, humidifier)"
  exit 1
fi
if ! [[ "$NAME" =~ ^[a-zA-Z0-9_-]{1,32}$ ]]; then
  echo "✗ The name must be alphanumeric/_/- (max 32 chars): it is the plug's MQTT username"
  echo "  and the one topic level its MQTT tree sits under."
  exit 1
fi
ACCOUNT="$(sp_service_account "$ROOT" "$NAME")"
if [ -n "$ACCOUNT" ]; then
  echo "✗ '$NAME' is the broker's '$ACCOUNT' service account, not a plug. Use the plug's own"
  echo "  name (its Tasmota Topic or Shelly role); rotate service accounts with"
  echo "  ./scripts/rotate-mqtt-creds.sh."
  exit 1
fi
if [ -d "$PASSWD" ]; then
  echo "✗ $PASSWD is a directory (Docker created it when the stack was started"
  echo "  before install.sh). Re-run ./install.sh — it repairs this — then retry."
  exit 1
fi

PASS=$(openssl rand -hex 16)

if sp_docker_init; then
  printf '%s\n%s\n' "$NAME" "$PASS" | sp_passwd_update "$ROOT"
elif command -v mosquitto_passwd >/dev/null 2>&1 && { [ ! -e "$PASSWD" ] || [ -w "$PASSWD" ]; }; then
  # No docker here (e.g. a bare-metal dev broker): edit with the host tool.
  sp_host_passwd_set "$PASSWD" "$NAME" "$PASS"
else
  echo "✗ Cannot edit $PASSWD: need a reachable docker daemon (the file belongs to"
  echo "  the broker's uid ${SP_BROKER_UID} on Linux), or mosquitto_passwd with write access."
  exit 1
fi

# The root .env is what compose hands the server; server/.env is the
# bare-metal server's own.
ENV_FILES=("$ROOT/.env")
[ -f "$ROOT/server/.env" ] && ENV_FILES+=("$ROOT/server/.env")
for f in "${ENV_FILES[@]}"; do
  listed="$(sp_env_get "$f" SPOREPRINT_MQTT_PLUG_USERS)"
  if ! printf '%s\n' "$listed" | tr ', ' '\n' | grep -ixF -- "$NAME" >/dev/null; then
    sp_env_set "$f" SPOREPRINT_MQTT_PLUG_USERS "${listed:+$listed,}$NAME"
  fi
done

sp_broker_reload "$ROOT"

DC_PREFIX=""; [ "$SP_DOCKER_MODE" = "sudo" ] && DC_PREFIX="sudo "
if sp_broker_running "$ROOT"; then
  # Recreate (not restart) so the server reads the new SPOREPRINT_MQTT_PLUG_USERS.
  sp_docker compose -f "$ROOT/docker-compose.yml" up -d server
  echo "✓ server recreated: it takes no node frames from '$NAME'"
else
  echo "Apply the plug list to the Pi server:"
  echo "  Docker:     cd $ROOT && ${DC_PREFIX}docker compose up -d server   (not 'restart')"
  echo "  Bare metal: sudo systemctl restart sporeprint"
fi

echo ""
echo "✓ Broker user '$NAME' created for one plug."
echo ""
echo "In the plug's MQTT settings, enter:"
echo "  Host / port:   the Pi's IP, port 1883"
echo "  User:          $NAME"
echo "  Password:      $PASS"
echo "  Tasmota:       Topic $NAME, Full Topic tasmota/%topic%/%prefix%/"
echo "  Shelly Gen2+:  MQTT prefix shellies/$NAME"
echo "  Shelly Gen1:   no topic setting: run this with the plug's device id instead"
echo ""
echo "(A plug already set up with the shared sp-3p login keeps working; move it to"
echo " this login and its password no longer reaches the other plugs. No node may"
echo " use the name '$NAME': the server ignores node frames under it.)"
