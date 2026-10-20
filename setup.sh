#!/usr/bin/env bash
#
# SporePrint — DEVELOPER workstation setup (Python venv, dev tooling, local
# secrets + broker credentials/certs for running the stack from a checkout).
#
#   NOT for installing a Pi. On a Raspberry Pi use the supported installer:
#       ./install.sh
#   (or: curl -fsSL https://raw.githubusercontent.com/59psi/SporePrint/main/install.sh | bash)
#   install.sh installs Docker, generates the broker credentials + TLS certs,
#   writes a LAN-trust .env and starts the stack.
#
# Like install.sh this runs the API in LAN-trust mode (no API key): the
# bundled browser dashboard calls /api same-origin WITHOUT a bearer token, so
# an API key would make every dashboard request 401. Set SPOREPRINT_API_KEY
# yourself if you need to gate the API for the mobile app / external clients.
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
fail()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
header() { echo -e "\n${BOLD}$1${NC}"; }

cd "$(dirname "$0")"
# shellcheck source=scripts/lib/broker.sh
. scripts/lib/broker.sh
# shellcheck source=scripts/lib/host.sh
. scripts/lib/host.sh

# ── Prerequisites ──────────────────────────────────────────────

header "Checking prerequisites..."

# uv — REQUIRED: it installs the server's locked dependencies (server/uv.lock,
# exactly what the image installs) on the image's Python, which it fetches
# itself when the host has none.
command -v uv &>/dev/null || fail "uv not found — install it (https://docs.astral.sh/uv/: curl -LsSf https://astral.sh/uv/install.sh | sh, or brew install uv) and re-run."
info "uv $(uv --version | awk '{print $2}')"

# openssl — REQUIRED: it generates every secret below, and the broker's TLS
# listener (8883) is always configured, so mosquitto refuses to start at all
# (taking plaintext 1883 down with it) until the certificates exist.
command -v openssl &>/dev/null || fail "openssl not found — install it (apt install openssl / brew install openssl) and re-run."
info "openssl $(openssl version | awk '{print $2}')"

# Docker (optional)
if command -v docker &>/dev/null; then
    info "Docker $(docker --version | sed -E 's/.*version ([0-9]+\.[0-9]+\.[0-9]+).*/\1/')"
else
    warn "Docker not found — needed for production deployment, not required for dev"
fi

# ── Environment ────────────────────────────────────────────────

header "Setting up environment..."

# _coordinate VALUE LIMIT — VALUE is a decimal number from -LIMIT to LIMIT.
_coordinate() {
    [[ "$1" =~ ^-?[0-9]+(\.[0-9]+)?$ ]] || return 1
    awk -v v="$1" -v m="$2" 'BEGIN { exit !(v + 0 >= -m && v + 0 <= m) }'
}

if [[ ! -f .env ]]; then
    cp .env.example .env
    # 0600 before anything secret goes in: an abort at a prompt below must not
    # leave the Claude key in a file every local user can read.
    chmod 600 .env
    info "Created .env from .env.example"

    echo ""
    read -rp "Enter your Claude API key (or press Enter to skip): " CLAUDE_KEY
    if [[ -z "$CLAUDE_KEY" ]]; then
        warn "Skipped Claude API key — vision analysis and builder's assistant won't work without it"
    elif [[ "$CLAUDE_KEY" =~ ^[A-Za-z0-9._+/=-]+$ ]]; then
        sp_env_set .env SPOREPRINT_CLAUDE_API_KEY "$CLAUDE_KEY"
        info "Claude API key saved to .env"
    else
        warn "That is not an API key (it has spaces, quotes or other characters a key never has) — not saved; set SPOREPRINT_CLAUDE_API_KEY in .env yourself"
    fi

    echo ""
    read -rp "Enter your latitude for weather (or press Enter to skip): " WEATHER_LAT
    if [[ -n "$WEATHER_LAT" ]]; then
        read -rp "Enter your longitude: " WEATHER_LON
        if _coordinate "$WEATHER_LAT" 90 && _coordinate "$WEATHER_LON" 180; then
            sp_env_set .env SPOREPRINT_WEATHER_LAT "$WEATHER_LAT"
            sp_env_set .env SPOREPRINT_WEATHER_LON "$WEATHER_LON"
            info "Weather location saved (using Open-Meteo — free, no API key needed)"
        else
            warn "Not saved: latitude must be -90 to 90 and longitude -180 to 180, in decimal degrees (e.g. 45.52 / -122.68) — set SPOREPRINT_WEATHER_LAT/LON in .env"
        fi
    else
        warn "Skipped weather — set SPOREPRINT_WEATHER_LAT/LON in .env to enable forecast automation"
    fi
else
    info ".env already exists"
fi

# ── Secrets: LAN-trust mode, MQTT credentials ──────────────────

header "Generating secrets..."

_gen_secret() { openssl rand -base64 36 | tr -d '=+/' | cut -c1-40; }
# .env reads and writes go through scripts/lib/host.sh: values as compose
# reads them, replaced in place or appended on a line of their own, and no
# secret on a command line.
_env_get() { sp_env_get .env "$1"; }

# LAN-trust (same as install.sh): leave the API ungated unless an API key was
# set explicitly. Generating a key here made the dashboard 401 on every call.
if [ -z "$(_env_get SPOREPRINT_API_KEY)" ] && [ -z "$(_env_get SPOREPRINT_ALLOW_UNAUTHENTICATED)" ]; then
    sp_env_set .env SPOREPRINT_ALLOW_UNAUTHENTICATED true
    info "LAN-trust mode (SPOREPRINT_ALLOW_UNAUTHENTICATED=true) — set SPOREPRINT_API_KEY to gate /api instead"
fi

# No broker login for the server yet (the key empty, or missing altogether).
if [ -z "$(_env_get SPOREPRINT_MQTT_USERNAME)" ]; then
    MQTT_SERVER_PASS=$(_gen_secret)
    sp_env_set .env SPOREPRINT_MQTT_USERNAME server
    sp_env_set .env SPOREPRINT_MQTT_PASSWORD "$MQTT_SERVER_PASS"

    # sp-3p is the credential you configure INTO Shelly/Tasmota smart plugs
    # (Tasmota: Configuration → MQTT → User/Password; Shelly Gen2+: Settings →
    # MQTT → Username/Password, with MQTT prefix shellies/<role>). The broker
    # refuses anonymous clients, so a plug configured with only Host+Port
    # never connects — and Mosquitto refuses silently.
    MQTT_3P_PASS=$(_gen_secret)
    sp_env_set .env SPOREPRINT_MQTT_3P_PASSWORD "$MQTT_3P_PASS"

    # Entries are set in place (existing per-node users are kept). On Linux
    # the dockerized broker needs the file owned by its uid (see
    # scripts/lib/broker.sh), so there the edit runs inside the broker image.
    if [ -d config/mosquitto/passwd ]; then
        fail "config/mosquitto/passwd is a directory (Docker created it) — remove it and re-run."
    elif sp_should_chown && sp_docker_init; then
        printf '%s\n%s\n%s\n%s\n' server "$MQTT_SERVER_PASS" sp-3p "$MQTT_3P_PASS" \
            | sp_passwd_update "$PWD"
        info "Mosquitto 'server' + 'sp-3p' (smart plug) users provisioned via docker"
    elif command -v mosquitto_passwd &>/dev/null; then
        sp_host_passwd_set config/mosquitto/passwd server "$MQTT_SERVER_PASS"
        sp_host_passwd_set config/mosquitto/passwd sp-3p "$MQTT_3P_PASS"
        info "Mosquitto 'server' + 'sp-3p' (smart plug) users provisioned"
    elif sp_docker_init; then
        printf '%s\n%s\n%s\n%s\n' server "$MQTT_SERVER_PASS" sp-3p "$MQTT_3P_PASS" \
            | sp_passwd_update "$PWD"
        info "Mosquitto 'server' + 'sp-3p' (smart plug) users provisioned via docker"
    else
        warn "Neither a reachable docker daemon nor mosquitto_passwd — run ./install.sh (Pi) or add them manually"
        warn "(each prompts for the password; type the value from .env):"
        warn "  mosquitto_passwd config/mosquitto/passwd server   # SPOREPRINT_MQTT_PASSWORD"
        warn "  mosquitto_passwd config/mosquitto/passwd sp-3p    # SPOREPRINT_MQTT_3P_PASSWORD"
    fi
    info "Smart plugs authenticate as sp-3p — password stored in .env (SPOREPRINT_MQTT_3P_PASSWORD)"
    info "ESP32 nodes each need their own broker user: ./scripts/add-node-mqtt-user.sh <node_id>"
fi

# Command-signing key — same as install.sh: with a key the Pi signs every
# cmd/* frame (unkeyed nodes accept signed frames), so a cloud-paired stack
# (signing enforced) never drops commands for want of one.
if [ -z "$(_env_get SPOREPRINT_MQTT_HMAC_KEY)" ]; then
    sp_ensure_signing_key "$PWD" >/dev/null
    info "Command-signing key in .env (SPOREPRINT_MQTT_HMAC_KEY) — print it with ./scripts/provision-node.sh"
fi

# Time zone for the automation schedules (compose passes TZ to the server).
if [ -z "$(_env_get TZ)" ]; then
    HOST_TZ="$(sp_host_timezone)"
    if [ -n "$HOST_TZ" ]; then
        sp_env_set .env TZ "$HOST_TZ"
        info "Time zone $HOST_TZ (TZ in .env — automation schedules follow it)"
    else
        warn "Could not determine the host time zone — schedules run on UTC; set TZ=<Region/City> in .env"
    fi
fi

chmod 600 .env 2>/dev/null || true

# ── Broker TLS certificates (v4.2) ─────────────────────────────
# Generates a local CA + a server certificate for mosquitto's 8883
# listener. Nodes pin the CA via trust-on-first-use: they fetch it once
# from /api/provision/ca at provision time (the portal's "Secure MQTT"
# toggle) and verify the broker against it from then on. TLS is opt-in per
# node, but the listener is not: mosquitto will not start without these.

header "Broker TLS certificates..."

CERT_DIR="config/mosquitto/certs"
HOST_NAME="$(hostname -s 2>/dev/null || echo sporeprint)"
# The server certificate names the mDNS name, the hostname AND every IPv4 of
# this machine (each as IP: and DNS: — see sp_server_san), so a node given
# this machine's IP as its Secure-MQTT broker host verifies the broker. The
# same list install.sh issues on a Pi.
HOST_IPS="$(sp_host_ipv4s)"
PRIMARY_IP="$(printf '%s\n' "$HOST_IPS" | head -1)"
issue_server_cert() { # (re)issue server.key + server.crt from the existing CA
    # shellcheck disable=SC2086  # HOST_IPS word-splits into one argument per IP
    sp_issue_server_cert "$CERT_DIR" "$HOST_NAME" $HOST_IPS
}
mkdir -p "$CERT_DIR"
# The dockerized broker opens the certificates after dropping to uid 1883:
# the directory must be searchable by it, and acl.conf readable, whatever
# umask made them.
chmod 755 "$CERT_DIR"
chmod 644 config/mosquitto/mosquitto.conf config/mosquitto/acl.conf 2>/dev/null \
    || warn "Could not chmod 644 config/mosquitto/*.conf — the dockerized broker must be able to read them"
if [ ! -f "$CERT_DIR/ca.crt" ]; then
    # Local CA (10 years — LAN-internal trust root, rotated by deleting the dir).
    openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
        -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" \
        -subj "/CN=SporePrint Local CA" 2>/dev/null || fail "CA certificate generation failed"
    chmod 600 "$CERT_DIR/ca.key"
    chmod 644 "$CERT_DIR/ca.crt"
    issue_server_cert || fail "server certificate generation failed"
    info "CA + server certificate generated in $CERT_DIR"
elif [ ! -f "$CERT_DIR/server.crt" ] || [ ! -f "$CERT_DIR/server.key" ]; then
    # Never a new CA while ca.crt exists: Secure-MQTT nodes have pinned it and
    # refuse any other until they are factory-reset. Re-issue from it.
    [ -r "$CERT_DIR/ca.key" ] || fail "$CERT_DIR has the CA certificate but not its key (ca.key), so the broker certificate cannot be re-issued. Restore ca.key, or delete $CERT_DIR to start a new CA (every Secure-MQTT node must then be factory-reset and provisioned again)."
    issue_server_cert || fail "server certificate generation failed"
    info "Re-issued the broker certificate from the existing CA (pinned nodes unaffected)"
    info "A running broker keeps the old one until: docker compose restart mqtt"
else
    # An older DNS-only certificate, this machine's IP changed, or the
    # certificate is about to expire: re-issue it from the SAME CA — nodes pin
    # the CA, not the cert.
    REISSUE_WHY="$(sp_cert_reissue_reason "$CERT_DIR" "$PRIMARY_IP")"
    if [ -z "$REISSUE_WHY" ]; then
        info "Certificates already present — skipping (delete $CERT_DIR to start a new CA)"
    elif [ -r "$CERT_DIR/ca.key" ] && issue_server_cert; then
        info "Re-issued the broker certificate ($REISSUE_WHY; same CA — pinned nodes unaffected)"
        info "A running broker keeps the old one until: docker compose restart mqtt"
    else
        warn "The broker certificate needs re-issuing ($REISSUE_WHY) but $CERT_DIR/ca.key could not issue one — Secure MQTT nodes must use sporeprint.local"
    fi
fi
if ! openssl x509 -in "$CERT_DIR/ca.crt" -noout -checkend $((365 * 86400)) >/dev/null 2>&1; then
    warn "The broker CA ($CERT_DIR/ca.crt) expires within a year; replacing it means re-provisioning every Secure-MQTT node."
fi

# The dockerized broker opens the passwd file + TLS key AFTER dropping to its
# uid 1883 — hand them over on Linux (no-op on macOS / Docker Desktop).
if sp_should_chown && [ -f config/mosquitto/passwd ]; then
    if sp_docker_init && sp_broker_own "$PWD" passwd certs/server.key; then
        info "Broker secrets handed to the broker user (uid ${SP_BROKER_UID})"
    else
        warn "Could not chown config/mosquitto/passwd + certs/server.key to uid ${SP_BROKER_UID};"
        warn "the dockerized broker cannot read them until you do: sudo chown ${SP_BROKER_UID}:${SP_BROKER_UID} config/mosquitto/passwd config/mosquitto/certs/server.key"
    fi
fi

# ── Python environment ─────────────────────────────────────────

header "Setting up Python environment..."

# server/.venv with exactly the locked dependencies (server/uv.lock, which the
# image installs) on the image's Python, dev tools included: the command
# AGENTS.md gives. A bare `uv sync` would drop the dev extra and may pick a
# newer Python.
(cd server && uv sync --python 3.12 --extra dev)
info "server/.venv synced from server/uv.lock (Python 3.12, dev tools included)"

# ── Done ───────────────────────────────────────────────────────

header "Setup complete!"
echo ""
echo "  Development:"
echo "    docker compose up -d mqtt                              # the credentialed broker"
echo "    cd server && uv run uvicorn app.main:socket_app --reload    # API on :8000"
echo "    (run from server/, the API reads server/.env, not the repo-root .env:"
echo "     copy the SPOREPRINT_* settings you need there. Keys it does not use,"
echo "     such as TZ or SPOREPRINT_MQTT_3P_PASSWORD, are ignored; export TZ in"
echo "     that shell for the schedule time zone.)"
echo ""
echo "  Docker Compose (all services, same as a Pi):"
echo "    docker compose up -d --build"
echo ""
echo "  The dashboard ships pre-built in ui/dist (its source is not in this repo)."
echo "  Installing on a Raspberry Pi? Use ./install.sh instead of this script."
echo ""
echo "  Tests:"
echo "    cd server && uv run ruff check app/ && uv run pytest      # Backend"
echo ""
