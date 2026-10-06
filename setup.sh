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

# Python 3.11+
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 11 ]]; then
        info "Python $PY_VER"
    else
        fail "Python 3.11+ required (found $PY_VER)"
    fi
else
    fail "Python 3 not found. Install Python 3.11+."
fi

# openssl — REQUIRED: it generates every secret below, and the broker's TLS
# listener (8883) is always configured, so mosquitto refuses to start at all
# (taking plaintext 1883 down with it) until the certificates exist.
command -v openssl &>/dev/null || fail "openssl not found — install it (apt install openssl / brew install openssl) and re-run."
info "openssl $(openssl version | awk '{print $2}')"

# Node 20+ — optional: only needed for UI tooling in ui/ (the Pi UI ships as
# a pre-built bundle in ui/dist).
HAVE_NODE=0
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [[ "$NODE_MAJOR" -ge 20 ]]; then
        info "Node.js $NODE_VER"
        HAVE_NODE=1
    else
        warn "Node.js 20+ needed for UI tooling (found $NODE_VER) — skipping UI dependencies"
    fi
else
    warn "Node.js not found — skipping UI dependencies (not needed to run the server)"
fi

# Docker (optional)
if command -v docker &>/dev/null; then
    info "Docker $(docker --version | sed -E 's/.*version ([0-9]+\.[0-9]+\.[0-9]+).*/\1/')"
else
    warn "Docker not found — needed for production deployment, not required for dev"
fi

# ── Environment ────────────────────────────────────────────────

header "Setting up environment..."

if [[ ! -f .env ]]; then
    cp .env.example .env
    info "Created .env from .env.example"

    echo ""
    read -rp "Enter your Claude API key (or press Enter to skip): " CLAUDE_KEY
    if [[ -n "$CLAUDE_KEY" ]]; then
        sed -i.bak "s|^SPOREPRINT_CLAUDE_API_KEY=.*|SPOREPRINT_CLAUDE_API_KEY=$CLAUDE_KEY|" .env
        rm -f .env.bak
        info "Claude API key saved to .env"
    else
        warn "Skipped Claude API key — vision analysis and builder's assistant won't work without it"
    fi

    echo ""
    read -rp "Enter your latitude for weather (or press Enter to skip): " WEATHER_LAT
    if [[ -n "$WEATHER_LAT" ]]; then
        read -rp "Enter your longitude: " WEATHER_LON
        sed -i.bak "s|^SPOREPRINT_WEATHER_LAT=.*|SPOREPRINT_WEATHER_LAT=$WEATHER_LAT|" .env
        sed -i.bak "s|^SPOREPRINT_WEATHER_LON=.*|SPOREPRINT_WEATHER_LON=$WEATHER_LON|" .env
        rm -f .env.bak
        info "Weather location saved (using Open-Meteo — free, no API key needed)"
    else
        warn "Skipped weather — set SPOREPRINT_WEATHER_LAT/LON in .env to enable forecast automation"
    fi
else
    info ".env already exists"
fi

# ── Data directories ───────────────────────────────────────────

header "Creating data directories..."

mkdir -p data/db data/vision data/mosquitto data/ntfy
info "data/db, data/vision, data/mosquitto, data/ntfy"

# ── Secrets: LAN-trust mode, MQTT credentials ──────────────────

header "Generating secrets..."

_gen_secret() { openssl rand -base64 36 | tr -d '=+/' | cut -c1-40; }
_env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }

# LAN-trust (same as install.sh): leave the API ungated unless an API key was
# set explicitly. Generating a key here made the dashboard 401 on every call.
if [ -z "$(_env_get SPOREPRINT_API_KEY)" ] && [ -z "$(_env_get SPOREPRINT_ALLOW_UNAUTHENTICATED)" ]; then
    sed -i.bak '/^SPOREPRINT_ALLOW_UNAUTHENTICATED=/d' .env && rm -f .env.bak
    echo "SPOREPRINT_ALLOW_UNAUTHENTICATED=true" >> .env
    info "LAN-trust mode (SPOREPRINT_ALLOW_UNAUTHENTICATED=true) — set SPOREPRINT_API_KEY to gate /api instead"
fi

if grep -q '^SPOREPRINT_MQTT_USERNAME=\s*$' .env 2>/dev/null; then
    MQTT_SERVER_PASS=$(_gen_secret)
    sed -i.bak "s|^SPOREPRINT_MQTT_USERNAME=.*|SPOREPRINT_MQTT_USERNAME=server|" .env
    sed -i.bak "s|^SPOREPRINT_MQTT_PASSWORD=.*|SPOREPRINT_MQTT_PASSWORD=$MQTT_SERVER_PASS|" .env
    rm -f .env.bak

    # sp-3p is the credential you configure INTO Shelly/Tasmota smart plugs
    # (Tasmota: Configuration → MQTT → User/Password; Shelly Gen2+: Settings →
    # MQTT → Username/Password, with MQTT prefix shellies/<role>). The broker
    # refuses anonymous clients, so a plug configured with only Host+Port
    # never connects — and Mosquitto refuses silently.
    MQTT_3P_PASS=$(_gen_secret)
    if grep -q '^SPOREPRINT_MQTT_3P_PASSWORD=' .env 2>/dev/null; then
        sed -i.bak "s|^SPOREPRINT_MQTT_3P_PASSWORD=.*|SPOREPRINT_MQTT_3P_PASSWORD=$MQTT_3P_PASS|" .env
        rm -f .env.bak
    else
        echo "SPOREPRINT_MQTT_3P_PASSWORD=$MQTT_3P_PASS" >> .env
    fi

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
        [ -f config/mosquitto/passwd ] || : > config/mosquitto/passwd
        mosquitto_passwd -b config/mosquitto/passwd server "$MQTT_SERVER_PASS"
        mosquitto_passwd -b config/mosquitto/passwd sp-3p "$MQTT_3P_PASS"
        chmod 600 config/mosquitto/passwd
        info "Mosquitto 'server' + 'sp-3p' (smart plug) users provisioned"
    elif sp_docker_init; then
        printf '%s\n%s\n%s\n%s\n' server "$MQTT_SERVER_PASS" sp-3p "$MQTT_3P_PASS" \
            | sp_passwd_update "$PWD"
        info "Mosquitto 'server' + 'sp-3p' (smart plug) users provisioned via docker"
    else
        warn "Neither a reachable docker daemon nor mosquitto_passwd — run ./install.sh (Pi) or add them manually:"
        warn "  mosquitto_passwd -b config/mosquitto/passwd server <SPOREPRINT_MQTT_PASSWORD from .env>"
        warn "  mosquitto_passwd -b config/mosquitto/passwd sp-3p <SPOREPRINT_MQTT_3P_PASSWORD from .env>"
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
    local tmp
    tmp="$(mktemp -d)"
    # shellcheck disable=SC2086  # HOST_IPS word-splits into one argument per IP
    if openssl req -newkey rsa:2048 -nodes \
           -keyout "$tmp/server.key" -out "$tmp/server.csr" \
           -subj "/CN=sporeprint.local" 2>/dev/null \
       && openssl x509 -req -in "$tmp/server.csr" \
           -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
           -CAcreateserial -CAserial "$tmp/ca.srl" \
           -days 1825 -out "$tmp/server.crt" \
           -extfile <(printf 'subjectAltName=%s' "$(sp_server_san "$HOST_NAME" $HOST_IPS)") 2>/dev/null; then
        chmod 600 "$tmp/server.key"
        chmod 644 "$tmp/server.crt"
        mv -f "$tmp/server.key" "$CERT_DIR/server.key"
        mv -f "$tmp/server.crt" "$CERT_DIR/server.crt"
        rm -rf "$tmp"
        return 0
    fi
    rm -rf "$tmp"
    return 1
}
if [ ! -f "$CERT_DIR/server.crt" ]; then
    mkdir -p "$CERT_DIR"
    # Local CA (10 years — LAN-internal trust root, rotated by deleting the dir).
    openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
        -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" \
        -subj "/CN=SporePrint Local CA" 2>/dev/null || fail "CA certificate generation failed"
    chmod 600 "$CERT_DIR/ca.key"
    chmod 644 "$CERT_DIR/ca.crt"
    issue_server_cert || fail "server certificate generation failed"
    info "CA + server certificate generated in $CERT_DIR"
elif [ -n "$PRIMARY_IP" ] && ! openssl x509 -in "$CERT_DIR/server.crt" -noout -text 2>/dev/null \
        | grep -qE "IP Address:$(printf '%s' "$PRIMARY_IP" | sed 's/\./\\./g')(,|\$)"; then
    # An older DNS-only certificate, or this machine's IP changed: re-issue the
    # server certificate from the SAME CA — nodes pin the CA, not the cert.
    if [ -r "$CERT_DIR/ca.key" ] && issue_server_cert; then
        info "Re-issued the broker certificate to cover $PRIMARY_IP (same CA — pinned nodes unaffected)"
        info "A running broker keeps the old one until: docker compose restart mqtt"
    else
        warn "The broker certificate does not cover $PRIMARY_IP — Secure MQTT nodes must use sporeprint.local"
    fi
else
    info "Certificates already present — skipping (delete $CERT_DIR to regenerate)"
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

if [[ ! -d .venv ]]; then
    python3 -m venv .venv
    info "Created virtual environment (.venv)"
else
    info "Virtual environment already exists"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -e "./server[dev]"
info "Installed server dependencies (including dev tools)"

# ── UI dependencies ────────────────────────────────────────────

header "Installing UI dependencies..."

if [[ "$HAVE_NODE" = "1" && -f ui/package.json ]]; then
    (cd ui && npm install --silent 2>/dev/null)
    info "Installed UI dependencies"
else
    warn "Skipped (needs Node.js 20+ and ui/package.json — the Pi UI ships pre-built in ui/dist)"
fi

# ── Done ───────────────────────────────────────────────────────

header "Setup complete!"
echo ""
echo "  Development:"
echo "    source .venv/bin/activate"
echo "    cd server && uvicorn app.main:socket_app --reload    # API on :8000"
echo "    (the server reads server/.env when run from server/ — copy the"
echo "     SPOREPRINT_* settings you need there; it refuses keys it does not"
echo "     know, such as TZ or SPOREPRINT_MQTT_3P_PASSWORD)"
echo ""
echo "  You'll also need the credentialed MQTT broker:"
echo "    docker compose up -d mqtt"
echo ""
echo "  Docker Compose (all services, same as a Pi):"
echo "    docker compose up -d --build"
echo ""
echo "  Installing on a Raspberry Pi? Use ./install.sh instead of this script."
echo ""
echo "  Tests:"
echo "    cd server && pytest                                  # Backend"
echo ""
