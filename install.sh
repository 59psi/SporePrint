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
#      (official get.docker.com convenience script), plus chrony (NTP; it
#      also serves time to the nodes on the LAN) and openssl if needed.
#      Nothing else has to be installed by hand.
#   3. Writes a LAN-trust .env and generates the secrets the stack needs:
#      the MQTT broker credentials (+ TLS certificates), a smart-plug
#      credential, the node command-signing key and an unguessable ntfy
#      topic; records the host's time zone (TZ) for the automation schedules.
#      Keys already set are kept. No secret is ever committed to git.
#   4. Brings the whole stack up with `docker compose up -d --build` and
#      waits for the API to report healthy and the server to reach the MQTT
#      broker.
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
# The containers read the checkout as other users (the broker as uid 1883,
# the server as uid 1000): a clone made under a stricter umask (077) left
# acl.conf, models/ and docs/ unreadable to them. Secrets get explicit modes
# (.env, ca.key, server.key and passwd are 0600).
umask 022

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
  # shellcheck disable=SC1091  # the host's own os-release, read at runtime
  OS_ID="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-unknown}" || true)"
  # shellcheck disable=SC1091
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

# ── 2. Time: chrony, also the LAN's time server ──────────────────────────────
# The Pi's clock keeps cloud command replay windows and log/telemetry
# timestamps right. Nodes in a room without internet take their time from
# the Pi (the setup portal's "NTP server"), and a node holding the
# command-signing key refuses every command until its clock is set. So the Pi
# answers NTP from private addresses (udp/123), from its own clock when it
# has no upstream either. chrony does both; systemd-timesyncd (Raspberry Pi
# OS's default) serves no clients, and installing chrony replaces it.
# Best-effort, never fatal.
step "Ensuring accurate time and a LAN time server (chrony)"
CHRONY_CONF="${SP_CHRONY_CONF:-/etc/chrony/chrony.conf}"
chrony_serve_lan() { # write the LAN-server drop-in, make chrony read it, restart it
  local dir dropin
  dir="$(dirname "$CHRONY_CONF")/conf.d"
  dropin="$dir/sporeprint.conf"
  printf '%s\n' \
    "# Written by SporePrint's install.sh: answer NTP from private (LAN) addresses" \
    "# so ESP32 nodes without internet access can set their clocks from this Pi." \
    "allow 10.0.0.0/8" "allow 172.16.0.0/12" "allow 192.168.0.0/16" \
    "# Serve this Pi's own clock when it has no upstream source either." \
    "local stratum 10" \
    | { $SUDO mkdir -p "$dir" && $SUDO tee "$dropin" >/dev/null; } || return 1
  # Debian's chrony.conf reads conf.d (confdir); include the file otherwise.
  if ! grep -Eq "^[[:space:]]*(confdir[[:space:]]+${dir}|include[[:space:]]+${dropin})[[:space:]]*\$" \
       "$CHRONY_CONF" 2>/dev/null; then
    printf 'include %s\n' "$dropin" | $SUDO tee -a "$CHRONY_CONF" >/dev/null || return 1
  fi
  command -v systemctl >/dev/null 2>&1 || return 2
  $SUDO systemctl enable chrony >/dev/null 2>&1 || true
  $SUDO systemctl restart chrony >/dev/null 2>&1 \
    || $SUDO systemctl restart chronyd >/dev/null 2>&1 || return 2
}
HAVE_CHRONY=0
if command -v chronyc >/dev/null 2>&1 || [ -x /usr/sbin/chronyd ]; then
  HAVE_CHRONY=1
elif command -v ntpd >/dev/null 2>&1 || [ -x /usr/sbin/ntpd ]; then
  info "ntpd keeps time here and answers NTP clients by default: nodes can use this Pi as their NTP server"
elif apt_install chrony >/dev/null 2>&1; then
  HAVE_CHRONY=1
  info "Installed chrony"
elif [ "$(timedatectl show -p NTP --value 2>/dev/null || true)" = "yes" ]; then
  warn "Could not install chrony. systemd-timesyncd keeps this Pi's clock but serves no clients:"
  warn "nodes cannot use this Pi as their NTP server (without internet they never get the time)."
else
  warn "Could not install chrony and no NTP client runs: this Pi's clock may drift (cloud commands"
  warn "are then refused as stale) and nodes cannot set their clocks from it."
fi
if [ "$HAVE_CHRONY" = "1" ]; then
  CHRONY_RC=0
  chrony_serve_lan || CHRONY_RC=$?
  case "$CHRONY_RC" in
    0) if $SUDO chronyc accheck 192.168.1.1 2>/dev/null | grep -i denied >/dev/null; then
         warn "chrony did not load $(dirname "$CHRONY_CONF")/conf.d/sporeprint.conf: nodes cannot use this Pi as their NTP server"
       else
         info "chrony keeps time and answers NTP from the LAN (udp/123: open it if this Pi runs a firewall)"
       fi ;;
    2) warn "chrony is set up to serve the LAN; restart it to apply (sudo systemctl restart chrony)" ;;
    *) warn "Could not write chrony's LAN config: nodes cannot use this Pi as their NTP server" ;;
  esac
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
# Keep env_get / env_set in step with scripts/lib/host.sh sp_env_get /
# sp_env_set (tests/test_provision_scripts.py holds both to compose's reading).
env_get() { # env_get KEY [FILE] — KEY's value as docker compose reads it, or nothing
  # The last line wins; surrounding quotes are removed (a double-quoted value
  # also unescapes \" \\ \$ \n \t \r); an unquoted value loses its outer
  # blanks and a trailing " # comment"; an `export ` prefix is allowed. Read
  # verbatim, a quoted password would be hashed into passwd with its quotes
  # while compose hands the server the bare value.
  [ -f "${2:-.env}" ] || return 0
  SP_ENV_KEY="$1" awk '
    BEGIN { k = ENVIRON["SP_ENV_KEY"] }
    {
      line = $0
      sub(/\r$/, "", line)
      sub(/^[ \t]*export[ \t]+/, "", line)
      if (index(line, k "=") != 1) next
      v = substr(line, length(k) + 2)
      sub(/^[ \t]+/, "", v)
      q = substr(v, 1, 1)
      if (q == "\"" || q == "\047") {
        out = ""
        for (i = 2; i <= length(v); i++) {
          c = substr(v, i, 1)
          if (c == q) break
          if (q == "\"" && c == "\\" && i < length(v)) {
            i++; c = substr(v, i, 1)
            if (c == "n") c = "\n"
            else if (c == "t") c = "\t"
            else if (c == "r") c = "\r"
            else if (c != "\\" && c != "\"" && c != "$") c = "\\" c
          }
          out = out c
        }
        v = out
      } else {
        sub(/[ \t]+#.*$/, "", v)
        sub(/[ \t]+$/, "", v)
      }
      last = v; found = 1
    }
    END { if (found) printf "%s", last }' "${2:-.env}"
}
env_set() { # env_set KEY VALUE — replace in place or append. Idempotent.
  # The value reaches awk in its environment, never on its command line (the
  # process table) or through -v (which rewrites backslash escapes). awk ends
  # every line it writes with a newline, so a last line saved without one
  # never has the new key glued onto it.
  local src=.env tmp
  [ -f .env ] || src=/dev/null
  tmp="$(mktemp)"
  SP_ENV_KEY="$1" SP_ENV_VAL="$2" awk '
    BEGIN { FS = OFS = "="; k = ENVIRON["SP_ENV_KEY"]; v = ENVIRON["SP_ENV_VAL"] }
    $1 == k { print k "=" v; seen = 1; next }
    { print }
    END { if (!seen) print k "=" v }' "$src" > "$tmp"
  mv "$tmp" .env
}

EXISTING_INSTALL=0
if [ ! -f .env ]; then
  if [ -f .env.example ]; then cp .env.example .env; info "Created .env from .env.example"
  else : > .env; info "Created empty .env"; fi
else
  EXISTING_INSTALL=1
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

# Command-signing key (SPOREPRINT_MQTT_HMAC_KEY). With a key the Pi signs
# every cmd/* frame: nodes that have no key accept signed frames, keyed nodes
# verify them. Without one, a cloud-paired Pi (mqtt_require_signing=auto)
# REFUSES every node command, so pairing a Pi whose nodes were never
# provisioned used to cut off all actuation. Reuse a key an older
# scripts/provision-node.sh left in server/.env — nodes may already hold it.
# Keep in step with scripts/lib/host.sh sp_ensure_signing_key.
if [ -z "$(env_get SPOREPRINT_MQTT_HMAC_KEY)" ]; then
  HMAC_KEY="$(env_get SPOREPRINT_MQTT_HMAC_KEY server/.env)"
  if [ -n "$HMAC_KEY" ]; then
    info "Reusing the command-signing key from server/.env"
  else
    HMAC_KEY="$(openssl rand -hex 32)"
    info "Generated the command-signing key (SPOREPRINT_MQTT_HMAC_KEY)"
  fi
  env_set SPOREPRINT_MQTT_HMAC_KEY "$HMAC_KEY"
  unset HMAC_KEY
fi

# ntfy alert topic. The bundled ntfy server has no logins: anyone who can
# reach port 8080 and knows the topic can read the alerts or post fake ones.
# A new install gets a topic nobody can guess. An existing one keeps the
# topic its phones subscribe to (a new one would silently cut them off) and
# is warned while that is still the default.
NTFY_TOPIC="$(env_get SPOREPRINT_NTFY_TOPIC)"
NTFY_TOPIC_GUESSABLE=0
if [ -z "$NTFY_TOPIC" ] || [ "$NTFY_TOPIC" = "sporeprint" ]; then
  if [ "$EXISTING_INSTALL" = "0" ]; then
    NTFY_TOPIC="sporeprint-$(openssl rand -hex 8)"
    env_set SPOREPRINT_NTFY_TOPIC "$NTFY_TOPIC"
    info "Generated the ntfy alert topic ${NTFY_TOPIC} (SPOREPRINT_NTFY_TOPIC)"
  else
    NTFY_TOPIC="sporeprint"
    NTFY_TOPIC_GUESSABLE=1
    warn "Alerts go to the default ntfy topic 'sporeprint', which anyone on your network can"
    warn "read and post fake alerts to. Unless you set your own in Settings → Notifications,"
    warn "put SPOREPRINT_NTFY_TOPIC=<a long random name> in .env, re-run ./install.sh and"
    warn "subscribe your phone to the new topic."
  fi
fi

# Time zone: automation schedules (photoperiod, time windows, cron) run on
# the server container's local clock, which is UTC unless compose passes TZ.
# Only fills an unset TZ — an operator's choice in .env is kept.
# Keep in step with scripts/lib/host.sh sp_host_timezone.
host_timezone() { # the host's canonical IANA zone, or nothing
  local zi="${SP_ZONEINFO_DIR:-/usr/share/zoneinfo}" tz="" real=""
  if command -v timedatectl >/dev/null 2>&1; then
    tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  fi
  if [ -z "$tz" ] && [ -r /etc/timezone ]; then
    tz="$(head -n 1 /etc/timezone 2>/dev/null | tr -d '[:space:]' || true)"
  fi
  if [ -z "$tz" ] && [ -L /etc/localtime ]; then
    tz="$(readlink /etc/localtime 2>/dev/null || true)"
    tz="${tz##*zoneinfo/}"
  fi
  # A legacy alias (US/Pacific) is a symlink on Debian hosts: resolve it. The
  # server image carries canonical zones only, and glibc runs an unknown TZ
  # on UTC without a word.
  if [ -n "$tz" ] && [ -L "$zi/$tz" ]; then
    real="$(readlink -f "$zi/$tz" 2>/dev/null || true)"
    case "$real" in */zoneinfo/*) tz="${real##*/zoneinfo/}" ;; esac
  fi
  tz="${tz#posix/}"
  printf '%s\n' "$tz" | grep -Eq '^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$' || return 0
  if [ -d "$zi" ] && [ ! -f "$zi/$tz" ]; then return 0; fi
  printf '%s' "$tz"
}
if [ -z "$(env_get TZ)" ]; then
  HOST_TZ="$(host_timezone)"
  if [ -n "$HOST_TZ" ]; then
    env_set TZ "$HOST_TZ"
    info "Time zone ${HOST_TZ} (TZ in .env — automation schedules follow it)"
    if [ "$EXISTING_INSTALL" = "1" ] && [ "$HOST_TZ" != "UTC" ] && [ "$HOST_TZ" != "Etc/UTC" ]; then
      warn "Schedules ran on UTC until now. Rule times you entered in UTC to compensate"
      warn "(photoperiod, time windows, cron) now read as ${HOST_TZ} — set them back to local"
      warn "time, or put TZ=UTC in .env and re-run to keep the old behaviour."
    fi
  else
    warn "Could not determine this host's time zone — automation schedules will run on UTC."
    warn "Set TZ=<Region/City> (e.g. America/Los_Angeles) in .env and re-run ./install.sh."
  fi
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
# acl.conf is opened after the drop to uid 1883 too: it must be world-readable
# however the checkout was made (git records no read bits). Mosquitto 2.1
# warns that a later release will refuse a world-readable acl_file: a broker
# upgrade must hand it to uid 1883 the way passwd is.
for f in config/mosquitto/mosquitto.conf config/mosquitto/acl.conf; do
  if [ -f "$f" ] && ! chmod 644 "$f" 2>/dev/null; then
    warn "Could not make $f readable to the broker (chmod 644 it, or it will not start)"
  fi
done
BROKER_CHOWN=0
[ "$(uname -s)" = "Linux" ] && BROKER_CHOWN=1
PASSWD_CHANGED=0
if [ ! -f "$PASSWD_FILE" ] || [ "$MQTT_CREDS_FRESH" = "1" ]; then
  # Set `server` + `sp-3p` IN PLACE (never `mosquitto_passwd -c` on an
  # existing file): per-node users added by scripts/add-node-mqtt-user.sh
  # survive a re-run, and the inode the running broker's bind mount points at
  # stays the same. Passwords travel on stdin, into the container and on to
  # mosquitto_passwd (password + confirmation), never on a command line: a
  # container's processes show in the Pi's process table.
  # shellcheck disable=SC2016  # the -c script expands inside the container
  printf '%s\n%s\n%s\n%s\n' server "$MQTT_PASS" sp-3p "$MQTT_3P_PASS" \
    | dc run --rm -i -e SP_CHOWN="$BROKER_CHOWN" \
        -v "$PWD/config/mosquitto:/work" --entrypoint sh "$MOSQUITTO_IMAGE" -c '
      set -e
      [ -f /work/passwd ] || : > /work/passwd
      while IFS= read -r u && IFS= read -r p; do
        printf "%s\n%s\n" "$p" "$p" | mosquitto_passwd /work/passwd "$u" >/dev/null
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
# Keep issue_server_cert / cert_reissue_reason in step with scripts/lib/host.sh
# sp_issue_server_cert / sp_cert_reissue_reason.
issue_server_cert() { # (re)issue server.key + server.crt from the CA in $CERT_DIR
  # Both are made in a directory inside $CERT_DIR (the same filesystem, so
  # each rename is atomic) and moved into place only once both exist; on any
  # failure the old pair stays and this returns 1.
  local tmp
  tmp="$(mktemp -d "$CERT_DIR/.issue.XXXXXX")" || return 1
  if openssl req -newkey rsa:2048 -nodes \
       -keyout "$tmp/server.key" -out "$tmp/server.csr" \
       -subj "/CN=sporeprint.local" 2>/dev/null \
     && openssl x509 -req -in "$tmp/server.csr" \
       -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
       -CAcreateserial -CAserial "$tmp/ca.srl" \
       -days 1825 -out "$tmp/server.crt" \
       -extfile <(printf 'subjectAltName=%s' "$(server_san)") 2>/dev/null \
     && chmod 600 "$tmp/server.key" && chmod 644 "$tmp/server.crt" \
     && mv -f "$tmp/server.key" "$CERT_DIR/server.key" \
     && mv -f "$tmp/server.crt" "$CERT_DIR/server.crt"; then
    rm -rf "$tmp"
    return 0
  fi
  rm -rf "$tmp"
  return 1
}
cert_reissue_reason() { # why server.crt must be re-issued from the CA, or nothing
  if ! openssl x509 -in "$CERT_DIR/server.crt" -noout -checkend $((30 * 86400)) >/dev/null 2>&1; then
    printf 'it expires within 30 days'
  elif [ -n "$PRIMARY_IP" ] && ! openssl x509 -in "$CERT_DIR/server.crt" -noout -text 2>/dev/null \
       | grep -E "IP Address:$(printf '%s' "$PRIMARY_IP" | sed 's/\./\\./g')(,|\$)" >/dev/null; then
    # (grep reads to the end: an early -q exit could SIGPIPE openssl, and
    # under pipefail that would read as "not covered".)
    printf 'it does not cover %s' "$PRIMARY_IP"
  fi
}
CERTS_CHANGED=0
CA_CHANGED=0
mkdir -p "$CERT_DIR"
# The broker opens the certificates after dropping to uid 1883, so the
# directory must be searchable by it whatever umask made it.
chmod 755 "$CERT_DIR" || fail "could not make $CERT_DIR searchable by the broker (chmod 755)"
if [ ! -f "$CERT_DIR/ca.crt" ]; then
  # No CA yet (or $CERT_DIR was deleted to start over): a new CA and a server
  # certificate from it. A node that pinned an earlier CA must be provisioned
  # again.
  openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
    -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" \
    -subj "/CN=SporePrint Local CA" 2>/dev/null || fail "CA certificate generation failed"
  chmod 600 "$CERT_DIR/ca.key"
  chmod 644 "$CERT_DIR/ca.crt"
  issue_server_cert || fail "server certificate generation failed"
  CERTS_CHANGED=1
  CA_CHANGED=1
  info "Generated CA + server certificate in $CERT_DIR"
elif [ ! -f "$CERT_DIR/server.crt" ] || [ ! -f "$CERT_DIR/server.key" ]; then
  # Never a new CA while ca.crt exists: Secure-MQTT nodes have pinned it and
  # refuse any other until they are factory-reset. Re-issue from it.
  [ -r "$CERT_DIR/ca.key" ] || fail "$CERT_DIR has the CA certificate but not its key (ca.key), so the broker certificate cannot be re-issued. Restore ca.key, or delete $CERT_DIR to start a new CA: every Secure-MQTT node must then be factory-reset and provisioned again."
  issue_server_cert || fail "server certificate generation failed"
  CERTS_CHANGED=1
  info "Re-issued the broker certificate from the existing CA (pinned nodes unaffected)"
else
  # Older installs issued a DNS-only certificate, the host's address can
  # change, and the certificate runs for five years: re-issue from the SAME
  # CA. Nodes pin the CA, so they keep verifying.
  REISSUE_WHY="$(cert_reissue_reason)"
  if [ -z "$REISSUE_WHY" ]; then
    info "TLS certificates already present — leaving as-is"
  elif [ -r "$CERT_DIR/ca.key" ] && issue_server_cert; then
    CERTS_CHANGED=1
    info "Re-issued the broker certificate (${REISSUE_WHY}; same CA — pinned nodes unaffected)"
  else
    warn "The broker certificate needs re-issuing (${REISSUE_WHY}) but $CERT_DIR/ca.key could not issue one."
    warn "Restore ca.key and re-run ./install.sh. Meanwhile nodes using Secure MQTT should use"
    warn "sporeprint.local (or ${HOST_NAME}.local) as the broker address."
  fi
fi
[ -f "$CERT_DIR/ca.crt" ] || fail "$CERT_DIR/ca.crt is missing — delete $CERT_DIR and re-run ./install.sh to regenerate the CA"
if ! openssl x509 -in "$CERT_DIR/ca.crt" -noout -checkend $((365 * 86400)) >/dev/null 2>&1; then
  warn "The broker CA ($CERT_DIR/ca.crt) expires within a year ($(openssl x509 -in "$CERT_DIR/ca.crt" -noout -enddate 2>/dev/null | cut -d= -f2))."
  warn "Replacing it means provisioning every Secure-MQTT node again: delete $CERT_DIR, re-run ./install.sh,"
  warn "then factory-reset and re-provision each node that uses Secure MQTT."
fi

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

# ── 9b. The server is on the broker ─────────────────────────────────────────
# /api/health answers as soon as uvicorn runs, broker or not. The mqtt
# healthcheck logs in as `server` with the password the server was given, so
# a passwd that does not match .env shows there; the server's own client is
# subscribed once the broker's $SYS stats reach /api/health/detail/mqtt.
step "Checking the server's MQTT connection"
mqtt_detail() { # GET /api/health/detail/mqtt; an API key goes to curl on stdin, never argv
  local key
  key="$(env_get SPOREPRINT_API_KEY)"
  if [ -n "$key" ]; then
    key="${key//\\/\\\\}"; key="${key//\"/\\\"}"   # curl config string escapes
    printf 'header = "Authorization: Bearer %s"\n' "$key" \
      | curl -fsS -K - "http://localhost:8000/api/health/detail/mqtt" 2>/dev/null
  else
    curl -fsS "http://localhost:8000/api/health/detail/mqtt" 2>/dev/null
  fi
}
MQTT_STATE="no broker container"
MQTT_CID="$(dc compose ps -q mqtt 2>/dev/null | head -1 || true)"
for _ in $(seq 1 30); do
  [ -n "$MQTT_CID" ] || break
  MQTT_STATE="$(dc inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$MQTT_CID" 2>/dev/null || true)"
  case "$MQTT_STATE" in healthy|unhealthy) break ;; esac
  printf '.'; sleep 2
done
SERVER_ON_MQTT=0
if [ "$MQTT_STATE" = "healthy" ]; then
  for _ in $(seq 1 15); do
    case "$(mqtt_detail || true)" in *'"version"'*) SERVER_ON_MQTT=1; break ;; esac
    printf '.'; sleep 2
  done
fi
printf '\n'
if [ "$SERVER_ON_MQTT" = "1" ]; then
  info "The server is connected to the MQTT broker"
else
  warn "The server is NOT connected to the MQTT broker (broker health: ${MQTT_STATE:-unknown})."
  warn "Nodes get no commands and their readings go nowhere until it is. Recent logs:"
  dc compose logs --tail=20 mqtt server || true
  warn "A broker login that does not match .env is the usual cause: rotate it with"
  warn "./scripts/rotate-mqtt-creds.sh server, then check: $( [ -n "$DOCKER_SUDO" ] && echo 'sudo ' )docker compose logs -f mqtt server"
fi

# ── 10. Summary ──────────────────────────────────────────────────────────────
PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[ -n "$PI_IP" ] || PI_IP="<pi-ip>"
DC_PREFIX=""; [ -n "$DOCKER_SUDO" ] && DC_PREFIX="sudo "
SCHED_TZ="$(env_get TZ)"; [ -n "$SCHED_TZ" ] || SCHED_TZ="UTC (set TZ in .env)"
if [ "$SERVER_ON_MQTT" = "1" ]; then
  RUNNING_LINE="${GREEN}${BOLD}✓ SporePrint is running.${NC}"
else
  RUNNING_LINE="${YELLOW}${BOLD}! SporePrint is up, but the server is not connected to the MQTT broker (see above).${NC}"
fi

cat <<EOF

${RUNNING_LINE}

  ${BOLD}Open the dashboard:${NC}  ${CYAN}http://${PI_IP}:3001${NC}
                        (or http://sporeprint.local:3001 if mDNS works on your network)

  API health   http://${PI_IP}:8000/api/health
  MQTT broker  ${PI_IP}:1883   (TLS on 8883)   — ESP32 nodes connect here
               Secure MQTT nodes: use sporeprint.local (or ${PI_IP}) as the broker host
  ntfy push    http://${PI_IP}:8080   topic ${NTFY_TOPIC}$( [ "$NTFY_TOPIC_GUESSABLE" = "1" ] && echo '  (the guessable default: see the warning above)' )
               (in the ntfy app, subscribe to that topic on http://${PI_IP}:8080)
  Schedules    ${SCHED_TZ} — photoperiod, time windows and cron rules follow it

${BOLD}Next steps${NC}
  • Open the dashboard and finish the first-run setup.
  • Pair firmware nodes to the broker: ./scripts/add-node-mqtt-user.sh <node_id>
  • Command signing is on: the Pi signs every node command. Nodes accept signed
    commands without the key; to make a node reject forged ones, paste the key
    into its portal's "Command signing key" — print it with ./scripts/provision-node.sh
  • Smart plugs (Shelly/Tasmota): give each its own MQTT login with
    ./scripts/add-plug-mqtt-user.sh <role> (or use the shared user sp-3p, password
    SPOREPRINT_MQTT_3P_PASSWORD in .env, which every such plug then holds).
    Tasmota: FullTopic tasmota/%topic%/%prefix%/ and Topic = the role;
    Shelly Plus/Pro/Mini/Gen3/Gen4: MQTT prefix shellies/<role>, e.g. shellies/humidifier.
  • To pair with the cloud (premium remote access), generate a code in the app.

${BOLD}Manage the stack${NC}  (from ${REPO_DIR})
  ${DC_PREFIX}docker compose ps                # service status
  ${DC_PREFIX}docker compose logs -f server    # live server logs
  ${DC_PREFIX}docker compose up -d server      # apply .env changes ('restart' does NOT re-read .env)
  ${DC_PREFIX}docker compose down              # stop everything (data is kept in named volumes)
  git pull && ./install.sh        # update the checkout + rebuild

${BOLD}Security${NC}
  Running in LAN-trust mode (no HTTP auth) — the browser UI is same-origin.
  Keep the Pi behind your router/NAT; do not port-forward it. To require an
  API key for the mobile app / external clients, set SPOREPRINT_API_KEY in
  ${REPO_DIR}/.env and run: ${DC_PREFIX}docker compose up -d server
  (the bundled browser dashboard sends no API key, so it stops working then).

EOF
