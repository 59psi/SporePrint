#!/usr/bin/env bash
# SporePrint — one-command Raspberry Pi setup.
#
# Installs Docker + Compose, clones the repo (if not already cloned), writes a
# minimal .env from .env.example, and starts the stack. Idempotent — you can
# re-run it to pick up updates.
#
# Usage:
#   # On a fresh Pi (Raspberry Pi OS 64-bit, bookworm or later):
#   curl -fsSL https://raw.githubusercontent.com/59psi/SporePrint/main/scripts/setup-pi.sh | bash
#
#   # Or, if you've already cloned the repo:
#   cd SporePrint && bash scripts/setup-pi.sh
#
# Tested on: Raspberry Pi 5 (4GB / 8GB), Pi 4 (4GB), Raspberry Pi OS 64-bit.
# Will probably work on Ubuntu Server / Debian 12 + arm64 — no Pi-specific
# packages are installed.

set -euo pipefail

REPO_URL="${SPOREPRINT_REPO_URL:-https://github.com/59psi/SporePrint.git}"
REPO_DIR="${SPOREPRINT_REPO_DIR:-$HOME/SporePrint}"
SKIP_START="${SPOREPRINT_SKIP_START:-0}"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*"; }

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    red "✗ required command not found: $1"
    return 1
  fi
}

step() { printf '\n\033[36m▶ %s\033[0m\n' "$*"; }

# ── 1. Sanity checks ────────────────────────────────────────────────────────

step "Checking system"
if [ "$(id -u)" = "0" ]; then
  red "Do not run this as root. It will sudo when it needs to."
  exit 1
fi
require_cmd bash
require_cmd sudo
require_cmd curl

OS="$(. /etc/os-release 2>/dev/null && echo "${ID:-unknown}")"
ARCH="$(uname -m)"
green "  OS: $OS ($ARCH)"

# ── 2. Ensure chrony is installed + active for NTP time sync ────────────────
#
# Why: the cloud relay rejects every command frame whose `ts` field is more
# than 30 s away from its own clock (see signing.py). On a headless Pi with a
# drifted RTC, every remote command silently fails with "ts outside replay
# window" and the failure surface is a user-reported support ticket. Chrony
# tracks multiple NTP sources in parallel, slews (not steps) the clock, and
# stays accurate to within a few milliseconds of pool.ntp.org — which is
# what Railway's host OS uses too, so cloud ↔ Pi drift stays well below the
# 30 s window.
step "Ensuring chrony (NTP time sync) is installed"
if command -v chronyc >/dev/null 2>&1; then
  green "  chrony already installed ($(chronyc -n tracking 2>/dev/null | head -1 || echo present))"
else
  yellow "  Installing chrony via apt…"
  sudo apt-get update -q
  sudo apt-get install -y chrony
fi

# Ensure the daemon is enabled + running. On Raspberry Pi OS the package
# ships enabled; this is defense-in-depth in case a prior admin disabled it.
if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl enable --now chrony 2>/dev/null || sudo systemctl enable --now chronyd 2>/dev/null || true
  # Emit a one-line status so the setup log shows sync offset + sources.
  if command -v chronyc >/dev/null 2>&1; then
    OFFSET="$(chronyc -n tracking 2>/dev/null | awk -F'[ ]+' '/System time/ {print $4, $5, $6}' || echo "unknown")"
    green "  chrony tracking offset: $OFFSET"
  fi
fi

# ── 3. Install Docker + Compose if missing ──────────────────────────────────

step "Ensuring Docker is installed"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  green "  Docker + compose plugin already installed ($(docker --version | head -1))"
else
  yellow "  Installing Docker Engine + Compose plugin via get.docker.com…"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  green "  Docker installed. You may need to log out and back in for the 'docker' group to take effect."
fi

if ! docker ps >/dev/null 2>&1; then
  yellow "  Docker is installed but not accessible to this user yet."
  yellow "  Either log out and back in, or run: newgrp docker"
  yellow "  Then re-run this script."
  exit 1
fi

# ── 3. Clone or update the repo ─────────────────────────────────────────────

step "Fetching SporePrint source → $REPO_DIR"
if [ -d "$REPO_DIR/.git" ]; then
  green "  Repo exists, pulling latest"
  git -C "$REPO_DIR" pull --recurse-submodules --ff-only
else
  green "  Cloning $REPO_URL"
  git clone --recurse-submodules "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"

# ── 4. Seed .env if missing ─────────────────────────────────────────────────

step "Ensuring .env exists"
if [ -f .env ]; then
  green "  .env already present"
else
  if [ -f .env.example ]; then
    cp .env.example .env
    green "  Copied .env.example → .env"
  else
    cat > .env <<'EOF'
# SporePrint Pi — local configuration.
# Fill in weather coordinates for forecast features. Everything else is optional.
SPOREPRINT_WEATHER_PROVIDER=openmeteo
SPOREPRINT_WEATHER_LAT=
SPOREPRINT_WEATHER_LON=
SPOREPRINT_WEATHER_POLL_MINUTES=10

# Optional: Claude API key for on-device AI features (or pair with cloud to use BYOK)
SPOREPRINT_CLAUDE_API_KEY=

# Set once the Pi has been paired with your cloud account. The mobile app
# writes these via POST /api/cloud/configure — no manual editing required.
SPOREPRINT_CLOUD_URL=
SPOREPRINT_CLOUD_DEVICE_ID=
SPOREPRINT_CLOUD_TOKEN=
EOF
    green "  Wrote default .env template"
  fi
  yellow "  Review .env and set SPOREPRINT_WEATHER_LAT / _LON for your location."
fi

# ── 5. Build + start the stack ──────────────────────────────────────────────

if [ "$SKIP_START" = "1" ]; then
  step "Skipping stack start (SPOREPRINT_SKIP_START=1)"
else
  step "Building + starting the Docker Compose stack"
  docker compose pull --ignore-pull-failures || true
  docker compose up -d --build

  step "Checking service health"
  sleep 3
  docker compose ps
fi

# ── 6. Summary ──────────────────────────────────────────────────────────────

PI_IP="$(hostname -I | awk '{print $1}')"

cat <<EOF

$(green "✓ SporePrint is ready.")

  Dashboard:  http://$PI_IP:3001   (or http://sporeprint.local:3001 if mDNS works on your network)
  API:        http://$PI_IP:8000/api/health
  MQTT:       $PI_IP:1883          (ESP32 nodes connect here)

Next steps:
  1. Open the dashboard and generate a 6-digit pairing code (Settings → Cloud Pairing).
  2. In the SporePrint mobile app, pair this Pi using the code.
  3. Docs: https://sporeprint.ai/docs/user-guide.md

Common commands:
  docker compose ps             # service status
  docker compose logs -f server # live logs
  docker compose restart server # restart after .env changes
  docker compose down           # stop everything
  bash scripts/setup-pi.sh      # re-run this script to pull updates + rebuild

EOF
