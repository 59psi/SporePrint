#!/usr/bin/env bash
# SporePrint — legacy Raspberry Pi setup entry point.
#
# Kept so old links keep working:
#   curl -fsSL https://raw.githubusercontent.com/59psi/SporePrint/main/scripts/setup-pi.sh | bash
#   cd SporePrint && bash scripts/setup-pi.sh
#
# It is now a thin wrapper around ./install.sh, the supported installer. The
# old body ran `docker compose up` without generating the broker password
# file, TLS certificates or the LAN-trust flag: Docker then created
# config/mosquitto/passwd and certs/ as root-owned DIRECTORIES, the broker
# and the server crash-looped while this script printed "ready", and every
# later install.sh run failed to write the password file. install.sh does all
# of that (and repairs a checkout this script previously broke).
#
# Environment overrides (also honoured by install.sh):
#   SPOREPRINT_REPO_URL   git URL to clone when piped   (default: 59psi/SporePrint)
#   SPOREPRINT_REPO_DIR   clone destination             (default: $HOME/SporePrint)
#   SPOREPRINT_SKIP_START  =1 to prepare everything but not start the stack

set -euo pipefail

REPO_URL="${SPOREPRINT_REPO_URL:-https://github.com/59psi/SporePrint.git}"
REPO_DIR="${SPOREPRINT_REPO_DIR:-$HOME/SporePrint}"

echo "scripts/setup-pi.sh is superseded by install.sh — running that instead."

# From a checkout: run that checkout's install.sh.
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
case "$SCRIPT_PATH" in
  ""|bash|sh|-*|/dev/*) SCRIPT_PATH="" ;;
esac
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
  ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
  if [ -f "$ROOT/install.sh" ]; then
    cd "$ROOT"
    exec bash "$ROOT/install.sh" "$@"
  fi
fi

# Piped (curl | bash): clone or update the repo, then run its install.sh.
if ! command -v git >/dev/null 2>&1; then
  echo "Installing git…"
  sudo apt-get update -q && sudo apt-get install -y git
fi
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull --recurse-submodules --ff-only \
    || echo "[!] git pull failed — using the existing checkout"
else
  git clone --recurse-submodules "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"
exec bash ./install.sh "$@"
