#!/usr/bin/env bash
#
# SporePrint Pi — one-command, dependency-complete installer.
#
#   curl -fsSL https://raw.githubusercontent.com/59psi/SporePrint/main/install.sh | bash
#
# or, from a checkout:
#
#   ./install.sh
#
# What it does (idempotent — safe to re-run to pick up updates):
#   1. Detects the OS (Raspberry Pi OS / Debian / Ubuntu).
#   2. Installs Docker Engine + the Compose plugin if they are missing
#      (official get.docker.com convenience script), plus chrony (NTP) and
#      openssl if needed. Nothing else has to be installed by hand.
#   3. Writes a LAN-trust .env and generates the secrets the stack needs:
#      the MQTT broker credentials (+ TLS certificates) and a smart-plug
#      credential. No secret is ever committed to git.
#   4. Brings the whole stack up with `docker compose up -d --build` and
#      waits for the API to report healthy.
#   5. Prints the dashboard URL.
#
# Security posture: the Pi runs in LAN-trust mode (see app/auth.py). The
# browser dashboard talks to the API same-origin with no bearer token, so
# there is no HTTP auth by default — keep the Pi behind your home router/NAT
# and never port-forward it. The MQTT broker is still credentialed. To gate
# the API for the mobile app / external clients, set SPOREPRINT_API_KEY in
# .env and run `docker compose up -d server` (see the README).
#
# Environment overrides:
#   SPOREPRINT_REPO_URL   git URL to clone when piped   (default: 59psi/SporePrint)
#   SPOREPRINT_REPO_DIR   clone destination             (default: $HOME/SporePrint)
#   SPOREPRINT_SKIP_START  =1 to prepare everything but not start the stack

set -euo pipefail

REPO_URL="${SPOREPRINT_REPO_URL:-https://github.com/59psi/SporePrint.git}"
REPO_DIR="${SPOREPRINT_REPO_DIR:-$HOME/SporePrint}"
SKIP_START="${SPOREPRINT_SKIP_START:-0}"

# The broker image — MUST equal services.mqtt.image in docker-compose.yml
# (tests/test_docker.py). Password hashes are generated inside it so their
# format always matches the broker that reads them.
MOSQUITTO_IMAGE="eclipse-mosquitto:2.1.2-alpine"

# ── Output helpers ───────────────────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; CYAN=$'\033[36m'; NC=$'\033[0m'
else
  BOLD=''; GREEN=''; YELLOW=''; RED=''; CYAN=''; NC=''
fi
info() { printf '%s[✓]%s %s\n' "$GREEN" "$NC" "$1"; }
warn() { printf '%s[!]%s %s\n' "$YELLOW" "$NC" "$1"; }
step() { printf '\n%s▶ %s%s\n' "$CYAN" "$1" "$NC"; }
fail() { printf '%s[✗] %s%s\n' "$RED" "$1" "$NC" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1 — install it and re-run ./install.sh"; }

# ── Privilege model ──────────────────────────────────────────────────────────
# Run as a normal user; escalate with sudo only where needed. Running as root
# is allowed too (SUDO becomes a no-op).
if [ "$(id -u)" = "0" ]; then
  SUDO=""
else
  require sudo
  SUDO="sudo"
fi

printf '%s\n' "${BOLD}SporePrint Pi installer${NC}"

# ── 1. System sanity + OS detection ──────────────────────────────────────────
step "Checking system"
require bash
require curl
ARCH="$(uname -m)"
OS_ID="unknown"; OS_LIKE=""
if [ -r /etc/os-release ]; then
  OS_ID="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-unknown}" || true)"
  OS_LIKE="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID_LIKE:-}" || true)"
fi
info "OS: ${OS_ID} (${ARCH})"
case "$OS_ID" in
  raspbian|debian|ubuntu) : ;;
  *) case "$OS_LIKE" in
       *debian*) : ;;
       *) warn "Untested OS '${OS_ID}'. Tested on Raspberry Pi OS / Debian / Ubuntu — continuing best-effort." ;;
     esac ;;
esac

HAVE_APT=0
command -v apt-get >/dev/null 2>&1 && HAVE_APT=1

apt_install() { # apt_install <pkg...> — best-effort; caller decides if fatal.
  [ "$HAVE_APT" = "1" ] || return 1
  $SUDO apt-get update -q && $SUDO apt-get install -y "$@"
}

# ── 2. NTP (chrony) — keeps the clock accurate so cloud command replay windows
#       and log/telemetry timestamps stay correct. Best-effort, never fatal. ──
step "Ensuring accurate time (chrony/NTP)"
if command -v chronyc >/dev/null 2>&1 || command -v timedatectl >/dev/null 2>&1; then
  info "Time sync already available"
elif apt_install chrony >/dev/null 2>&1; then
  command -v systemctl >/dev/null 2>&1 && $SUDO systemctl enable --now chrony >/dev/null 2>&1 || true
  info "Installed chrony"
else
  warn "Could not install chrony — ensure NTP time sync is enabled if you later pair with the cloud."
fi

# ── 3. Docker Engine + Compose plugin ────────────────────────────────────────
step "Ensuring Docker + Compose plugin"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  info "Docker present: $(docker --version)"
else
  warn "Installing Docker Engine + Compose plugin via get.docker.com…"
  curl -fsSL https://get.docker.com | $SUDO sh || fail "Docker installation failed. See https://docs.docker.com/engine/install/"
  if [ -n "$SUDO" ] && [ -n "${USER:-}" ]; then
    $SUDO usermod -aG docker "$USER" 2>/dev/null || true
  fi
  info "Docker installed: $(docker --version 2>/dev/null || echo 'installed')"
fi

# Decide whether we can reach the daemon directly, or must fall back to sudo
# (the 'docker' group only takes effect after a re-login, so a first-ever
# install still needs to work in a single run).
DOCKER_SUDO=""
if docker info >/dev/null 2>&1; then
  DOCKER_SUDO=""
elif [ -n "$SUDO" ] && sudo docker info >/dev/null 2>&1; then
  DOCKER_SUDO="sudo"
  warn "Your user isn't in the 'docker' group yet — using 'sudo docker' for this run."
  warn "Log out and back in (or run: newgrp docker) to use docker without sudo afterwards."
else
  fail "Docker is installed but its daemon isn't reachable. Start it (sudo systemctl start docker) or re-login, then re-run ./install.sh"
fi
dc() { if [ -n "$DOCKER_SUDO" ]; then sudo docker "$@"; else docker "$@"; fi; }

# ── 4. Locate the repo (in-place) or clone it (curl | bash) ───────────────────
step "Locating SporePrint source"
SCRIPT_DIR=""
case "${0:-}" in
  bash|sh|-*|/dev/*|"") : ;;                                   # piped — no script path
  *) SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)" ;;
esac
if [ -f "$PWD/docker-compose.yml" ] && [ -d "$PWD/server" ]; then
  REPO_DIR="$PWD"; info "Using checkout at $REPO_DIR"
elif [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/docker-compose.yml" ] && [ -d "$SCRIPT_DIR/server" ]; then
  REPO_DIR="$SCRIPT_DIR"; info "Using checkout at $REPO_DIR"
else
  require git
  if [ -d "$REPO_DIR/.git" ]; then
    info "Updating existing checkout at $REPO_DIR"
    git -C "$REPO_DIR" pull --recurse-submodules --ff-only || warn "git pull failed — building from the existing checkout"
  else
    info "Cloning $REPO_URL → $REPO_DIR"
    git clone --recurse-submodules "$REPO_URL" "$REPO_DIR" || fail "git clone failed"
  fi
fi
cd "$REPO_DIR" || fail "cannot cd into $REPO_DIR"

# ── 4b. Repair bind-mount sources Docker auto-created as directories ─────────
# A `docker compose up` that ran before these files existed (the old
# scripts/setup-pi.sh, or a bare `up` with the pre-long-syntax compose file)
# made Docker create each missing source as an EMPTY root-owned DIRECTORY.
# The broker then dies ("pwfile is a directory") and writing the real file
# fails. Remove them, and recreate the containers that mounted them (a mere
# restart would try to mount the new FILE onto the old directory mountpoint).
REPAIRED_MOUNTS=0
for p in config/mosquitto/passwd config/mosquitto/certs/ca.crt; do
  if [ -d "$p" ]; then
    $SUDO rmdir "$p" 2>/dev/null \
      || fail "$p is a directory (created by Docker) and is not empty — move it aside and re-run ./install.sh"
    warn "Removed Docker-created directory $p (it must be a file)"
    REPAIRED_MOUNTS=1
  fi
done
if [ -d config/mosquitto/certs ] && [ ! -w config/mosquitto/certs ]; then
  $SUDO chown "$(id -u):$(id -g)" config/mosquitto/certs
  warn "Reclaimed Docker-created config/mosquitto/certs for $(id -un)"
  REPAIRED_MOUNTS=1
fi

# ── 5. .env — LAN-trust config + generated secrets ───────────────────────────
step "Preparing configuration (.env)"

gen_secret() { openssl rand -base64 36 2>/dev/null | tr -d '=+/ ' | cut -c1-40; }
env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
env_set() { # env_set KEY VALUE — replace in place or append. Idempotent.
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" .env 2>/dev/null; then
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' .env > "$tmp"
  else
    cat .env > "$tmp" 2>/dev/null || true
    printf '%s=%s\n' "$key" "$val" >> "$tmp"
  fi
  mv "$tmp" .env
}

if [ ! -f .env ]; then
  if [ -f .env.example ]; then cp .env.example .env; info "Created .env from .env.example"
  else : > .env; info "Created empty .env"; fi
else
  info ".env already present — updating only unset keys"
fi

# openssl is needed for secret + certificate generation.
if ! command -v openssl >/dev/null 2>&1; then
  apt_install openssl >/dev/null 2>&1 || true
  command -v openssl >/dev/null 2>&1 || fail "openssl not found and could not be installed — install it and re-run ./install.sh"
fi

# LAN-trust: the same-origin browser UI carries no bearer, so leave the API
# ungated unless the operator has explicitly set an API key.
if [ -z "$(env_get SPOREPRINT_API_KEY)" ] && [ -z "$(env_get SPOREPRINT_ALLOW_UNAUTHENTICATED)" ]; then
  env_set SPOREPRINT_ALLOW_UNAUTHENTICATED "true"
  info "Set LAN-trust mode (SPOREPRINT_ALLOW_UNAUTHENTICATED=true)"
fi

# MQTT broker credentials for the Pi server ('server') + smart plugs ('sp-3p').
MQTT_CREDS_FRESH=0
MQTT_PASS="$(env_get SPOREPRINT_MQTT_PASSWORD)"
if [ -z "$MQTT_PASS" ]; then
  MQTT_PASS="$(gen_secret)"
  env_set SPOREPRINT_MQTT_USERNAME "server"
  env_set SPOREPRINT_MQTT_PASSWORD "$MQTT_PASS"
  MQTT_CREDS_FRESH=1
  info "Generated MQTT 'server' credentials"
fi
MQTT_3P_PASS="$(env_get SPOREPRINT_MQTT_3P_PASSWORD)"
if [ -z "$MQTT_3P_PASS" ]; then
  MQTT_3P_PASS="$(gen_secret)"
  env_set SPOREPRINT_MQTT_3P_PASSWORD "$MQTT_3P_PASS"
  MQTT_CREDS_FRESH=1
  info "Generated MQTT 'sp-3p' (smart-plug) credential"
fi
chmod 600 .env 2>/dev/null || true

# ── 6. Mosquitto password file (hashes generated inside the broker image) ─────
# Ownership matters: mosquitto drops to its `mosquitto` user (uid/gid 1883 in
# the image) right after reading mosquitto.conf and BEFORE it opens
# password_file or the TLS keyfile. A 0600 file owned by this (host) user is
# unreadable to it — "Unable to open pwfile" — and the broker crash-loops.
# So on Linux the broker's secret files belong to 1883:1883 (mode 0600), and
# every edit runs as root inside a throwaway broker container (the host user
# can no longer write them). Docker Desktop (macOS) maps ownership itself.
# Keep in step with scripts/lib/broker.sh.
step "Provisioning MQTT broker credentials"
PASSWD_FILE="config/mosquitto/passwd"
mkdir -p config/mosquitto
BROKER_CHOWN=0
[ "$(uname -s)" = "Linux" ] && BROKER_CHOWN=1
PASSWD_CHANGED=0
if [ ! -f "$PASSWD_FILE" ] || [ "$MQTT_CREDS_FRESH" = "1" ]; then
  # Set `server` + `sp-3p` IN PLACE (never `mosquitto_passwd -c` on an
  # existing file): per-node users added by scripts/add-node-mqtt-user.sh
  # survive a re-run, and the inode the running broker's bind mount points at
  # stays the same. Credentials travel on stdin, not argv.
  printf '%s\n%s\n%s\n%s\n' server "$MQTT_PASS" sp-3p "$MQTT_3P_PASS" \
    | dc run --rm -i -e SP_CHOWN="$BROKER_CHOWN" \
        -v "$PWD/config/mosquitto:/work" --entrypoint sh "$MOSQUITTO_IMAGE" -c '
      set -e
      [ -f /work/passwd ] || : > /work/passwd
      while IFS= read -r u && IFS= read -r p; do
        mosquitto_passwd -b /work/passwd "$u" "$p" >/dev/null
      done
      grep -q "^server:" /work/passwd
      grep -q "^sp-3p:" /work/passwd
      if [ "$SP_CHOWN" = "1" ]; then chown 1883:1883 /work/passwd; fi
      chmod 600 /work/passwd' \
    || fail "failed to write the mosquitto password file ($PASSWD_FILE)"
  PASSWD_CHANGED=1
  info "Wrote server + sp-3p into $PASSWD_FILE (other users kept)"
else
  info "$PASSWD_FILE already present — leaving its users as-is"
fi

# ── 7. Broker TLS certificates (8883 listener; nodes pin the CA) ──────────────
step "Provisioning MQTT TLS certificates"
CERT_DIR="config/mosquitto/certs"
HOST_NAME="$(hostname -s 2>/dev/null || echo sporeprint)"
# Every IPv4 address of this host goes into the broker certificate, so a node
# provisioned with the Pi's IP as its broker host passes the TLS name check
# (with a CA already pinned there is no plaintext fallback — a mismatch means
# the node never connects). Each IP is listed twice: IP:<ip> for standard
# clients (mosquitto_sub, Python), and DNS:<ip> because arduino-esp32 2.x
# (mbedTLS 2.28) compares the host string against SAN entries verbatim and
# cannot match an iPAddress entry. mDNS (sporeprint.local) stays the most
# robust broker address — a DHCP change moves the IP.
HOST_IPS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' || true)"
PRIMARY_IP="$(printf '%s\n' "$HOST_IPS" | head -1)"
server_san() {
  local san="DNS:sporeprint.local,DNS:${HOST_NAME}.local,DNS:${HOST_NAME},DNS:localhost,IP:127.0.0.1" ip
  for ip in $HOST_IPS; do san="${san},IP:${ip},DNS:${ip}"; done
  printf '%s' "$san"
}
issue_server_cert() { # (re)issue server.key + server.crt from the existing CA
  local tmp
  tmp="$(mktemp -d)"
  if openssl req -newkey rsa:2048 -nodes \
       -keyout "$tmp/server.key" -out "$tmp/server.csr" \
       -subj "/CN=sporeprint.local" 2>/dev/null \
     && openssl x509 -req -in "$tmp/server.csr" \
       -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
       -CAcreateserial -CAserial "$tmp/ca.srl" \
       -days 1825 -out "$tmp/server.crt" \
       -extfile <(printf 'subjectAltName=%s' "$(server_san)") 2>/dev/null; then
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
CERTS_CHANGED=0
CA_CHANGED=0
if [ ! -f "$CERT_DIR/server.crt" ]; then
  mkdir -p "$CERT_DIR"
  openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
    -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" \
    -subj "/CN=SporePrint Local CA" 2>/dev/null || fail "CA certificate generation failed"
  chmod 600 "$CERT_DIR/ca.key"
  chmod 644 "$CERT_DIR/ca.crt"
  issue_server_cert || fail "server certificate generation failed"
  CERTS_CHANGED=1
  CA_CHANGED=1
  info "Generated CA + server certificate in $CERT_DIR"
elif [ -n "$PRIMARY_IP" ] && ! openssl x509 -in "$CERT_DIR/server.crt" -noout -text 2>/dev/null \
       | grep -qE "IP Address:$(printf '%s' "$PRIMARY_IP" | sed 's/\./\\./g')(,|\$)"; then
  # Older installs issued a DNS-only certificate. Re-issue just the server
  # certificate from the SAME CA — nodes pin the CA, so they keep verifying.
  if [ -r "$CERT_DIR/ca.key" ] && issue_server_cert; then
    CERTS_CHANGED=1
    info "Re-issued the broker certificate to cover ${PRIMARY_IP} (same CA — pinned nodes unaffected)"
  else
    warn "The broker certificate does not cover ${PRIMARY_IP}. Nodes using Secure MQTT must use"
    warn "sporeprint.local (or ${HOST_NAME}.local) as the broker address."
  fi
else
  info "TLS certificates already present — leaving as-is"
fi
[ -f "$CERT_DIR/ca.crt" ] || fail "$CERT_DIR/ca.crt is missing — delete $CERT_DIR and re-run ./install.sh to regenerate the CA"

# ── 7b. Hand the broker's secret files to the broker user (Linux) ─────────────
# Idempotent, and also repairs installs made by older versions of this script
# (passwd + server.key owned by the host user → the broker could not start).
if [ "$BROKER_CHOWN" = "1" ]; then
  dc run --rm -v "$PWD/config/mosquitto:/work" --entrypoint sh "$MOSQUITTO_IMAGE" -c \
    'chown 1883:1883 /work/passwd /work/certs/server.key && chmod 600 /work/passwd /work/certs/server.key' \
    || fail "could not hand $PASSWD_FILE + $CERT_DIR/server.key to the broker user (uid 1883)"
  info "Broker secrets owned by the broker user (uid 1883, mode 0600)"
fi

# ── 8. Build + start the stack ───────────────────────────────────────────────
if [ "$SKIP_START" = "1" ]; then
  step "Skipping start (SPOREPRINT_SKIP_START=1) — run 'docker compose up -d --build' when ready"
  exit 0
fi

step "Building and starting the stack (this can take a few minutes on first run)"
if [ "$REPAIRED_MOUNTS" = "1" ]; then
  # Their mountpoints were created as directories — recreate, don't restart.
  dc compose rm -s -f mqtt server >/dev/null 2>&1 || true
fi
MQTT_WAS_RUNNING="$(dc compose ps -q --status running mqtt 2>/dev/null || true)"
SERVER_WAS_RUNNING="$(dc compose ps -q --status running server 2>/dev/null || true)"
dc compose pull --ignore-pull-failures >/dev/null 2>&1 || true
dc compose up -d --build || fail "docker compose failed to start the stack. Inspect: $( [ -n "$DOCKER_SUDO" ] && echo 'sudo ' )docker compose logs"
if [ -n "$MQTT_WAS_RUNNING" ] && { [ "$PASSWD_CHANGED" = "1" ] || [ "$CERTS_CHANGED" = "1" ]; }; then
  # A broker that was already running still holds the old users / old
  # certificate. (For passwd alone `docker compose kill -s HUP mqtt` would
  # do; the TLS certificate needs a restart.)
  dc compose restart mqtt >/dev/null || warn "could not restart the broker — run: docker compose restart mqtt"
  info "Broker restarted to load the new credentials / certificate"
fi
if [ -n "$SERVER_WAS_RUNNING" ] && [ "$CA_CHANGED" = "1" ]; then
  # ca.crt is a single-file bind mount: a running container keeps the OLD
  # file's inode until it is restarted, and would keep serving the old CA
  # from /api/provision/ca.
  dc compose restart server >/dev/null || warn "could not restart the server — run: docker compose restart server"
fi

# ── 9. Wait for the API to report healthy ────────────────────────────────────
step "Waiting for the API to come up"
HEALTHY=0
for _ in $(seq 1 45); do
  if curl -fsS "http://localhost:8000/api/health" >/dev/null 2>&1; then HEALTHY=1; break; fi
  printf '.'; sleep 2
done
printf '\n'
if [ "$HEALTHY" != "1" ]; then
  warn "API did not report healthy within ~90s. Recent server logs:"
  dc compose ps || true
  dc compose logs --tail=40 server || true
  fail "Stack started but the API is not healthy yet. Re-check with: $( [ -n "$DOCKER_SUDO" ] && echo 'sudo ' )docker compose logs -f server"
fi
info "API is healthy"

# ── 10. Summary ──────────────────────────────────────────────────────────────
PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[ -n "$PI_IP" ] || PI_IP="<pi-ip>"
DC_PREFIX=""; [ -n "$DOCKER_SUDO" ] && DC_PREFIX="sudo "

cat <<EOF

${GREEN}${BOLD}✓ SporePrint is running.${NC}

  ${BOLD}Open the dashboard:${NC}  ${CYAN}http://${PI_IP}:3001${NC}
                        (or http://sporeprint.local:3001 if mDNS works on your network)

  API health   http://${PI_IP}:8000/api/health
  MQTT broker  ${PI_IP}:1883   (TLS on 8883)   — ESP32 nodes connect here
               Secure MQTT nodes: use sporeprint.local (or ${PI_IP}) as the broker host
  ntfy push    http://${PI_IP}:8080

${BOLD}Next steps${NC}
  • Open the dashboard and finish the first-run setup.
  • Pair firmware nodes to the broker: ./scripts/add-node-mqtt-user.sh <node_id>
  • Optional command signing: ./scripts/provision-node.sh
  • To pair with the cloud (premium remote access), generate a code in the app.

${BOLD}Manage the stack${NC}  (from ${REPO_DIR})
  ${DC_PREFIX}docker compose ps                # service status
  ${DC_PREFIX}docker compose logs -f server    # live server logs
  ${DC_PREFIX}docker compose up -d server      # apply .env changes ('restart' does NOT re-read .env)
  ${DC_PREFIX}docker compose down              # stop everything (data is kept in named volumes)
  ./install.sh                     # re-run to update + rebuild

${BOLD}Security${NC}
  Running in LAN-trust mode (no HTTP auth) — the browser UI is same-origin.
  Keep the Pi behind your router/NAT; do not port-forward it. To require an
  API key for the mobile app / external clients, set SPOREPRINT_API_KEY in
  ${REPO_DIR}/.env and run: ${DC_PREFIX}docker compose up -d server
  (the bundled browser dashboard sends no API key, so it stops working then).

EOF
