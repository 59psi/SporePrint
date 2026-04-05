#!/usr/bin/env bash
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

# Node 20+
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [[ "$NODE_MAJOR" -ge 20 ]]; then
        info "Node.js $NODE_VER"
    else
        fail "Node.js 20+ required (found $NODE_VER)"
    fi
else
    fail "Node.js not found. Install Node.js 20+."
fi

# Docker (optional)
if command -v docker &>/dev/null; then
    info "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)"
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
else
    info ".env already exists"
fi

# ── Data directories ───────────────────────────────────────────

header "Creating data directories..."

mkdir -p data/db data/vision data/mosquitto data/ntfy
info "data/db, data/vision, data/mosquitto, data/ntfy"

# ── Python environment ─────────────────────────────────────────

header "Setting up Python environment..."

if [[ ! -d .venv ]]; then
    python3 -m venv .venv
    info "Created virtual environment (.venv)"
else
    info "Virtual environment already exists"
fi

source .venv/bin/activate
pip install -q -e "./server[dev]"
info "Installed server dependencies (including dev tools)"

# ── UI dependencies ────────────────────────────────────────────

header "Installing UI dependencies..."

cd ui
npm install --silent 2>/dev/null
cd ..
info "Installed UI dependencies"

# ── Done ───────────────────────────────────────────────────────

header "Setup complete!"
echo ""
echo "  Development:"
echo "    source .venv/bin/activate"
echo "    cd server && uvicorn app.main:socket_app --reload    # API on :8000"
echo "    cd ui && npm run dev                                 # UI on :3001"
echo ""
echo "  You'll also need an MQTT broker running:"
echo "    docker run -d -p 1883:1883 eclipse-mosquitto:2"
echo ""
echo "  Docker Compose (all services):"
echo "    docker compose up -d"
echo ""
echo "  Tests:"
echo "    cd server && pytest                                  # Backend"
echo "    cd ui && npm test                                    # Frontend"
echo ""
