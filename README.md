# SporePrint

Automated mushroom cultivation system for a single grow closet. Supports gourmet, medicinal, and active species with full environmental automation, dual vision pipeline, and Claude-powered analysis.

## Architecture

```
ESP32 Nodes ──MQTT──▶ Raspberry Pi Backend ◀──REST/WS──▶ React UI
  (sensors,            (FastAPI, SQLite,                  (dashboard,
   relays,              automation engine,                 sessions,
   lighting,            vision pipeline,                   vision,
   camera)              ntfy notifications)                transcripts)
```

**Hardware layer**: ESP32 sensor/actuator nodes (climate, relay/SSR, lighting, camera) + Shelly/Tasmota smart plugs, all communicating via MQTT.

**Backend**: FastAPI on Raspberry Pi 4/5. SQLite for storage. Mosquitto MQTT broker. Declarative automation rules engine. Dual vision pipeline (local CNN for fast contamination alerts, Claude API for deep analysis). ntfy for push notifications.

**Frontend**: React 18 + TypeScript + Vite + Tailwind. Real-time WebSocket updates. PWA-capable. Dark theme optimized for checking in dark closets.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose (for deployment)
- PlatformIO (for firmware, optional)

### Development

```bash
# Clone and enter project
git clone <repo-url> && cd SporePrint

# Backend
cd server
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Edit with your settings
uvicorn app.main:socket_app --reload

# Frontend (separate terminal)
cd ui
npm install
npm run dev

# MQTT broker (separate terminal, or use Docker)
docker run -d -p 1883:1883 -p 9001:9001 eclipse-mosquitto:2
```

The UI is available at `http://localhost:3001`, API at `http://localhost:8000`.

### Docker Compose (Production)

```bash
cp .env.example .env  # Edit with your settings
docker compose up -d
```

Services: backend (:8000), MQTT (:1883), ntfy (:8080), UI (:3001).

## Project Structure

```
SporePrint/
├── firmware/                  # ESP32 PlatformIO monorepo
│   ├── lib/sporeprint_common/   # Shared: WiFi, MQTT, OTA, heartbeat, offline buffer
│   └── src/
│       ├── climate_node/      # SHT31, SCD40, BH1750 sensors
│       ├── relay_node/        # IRLZ44N SSR control (4ch PWM)
│       ├── lighting_node/     # Multi-channel LED (white, blue, red, far-red)
│       └── cam_node/          # ESP32-CAM MJPEG + frame POST
├── server/                    # Python FastAPI backend
│   └── app/
│       ├── main.py            # App entrypoint + Socket.IO
│       ├── config.py          # Pydantic settings (env vars)
│       ├── db.py              # SQLite schema + connection manager
│       ├── mqtt.py            # MQTT subscriber + message routing
│       ├── telemetry/         # Sensor data ingest + history queries
│       ├── sessions/          # Grow session lifecycle
│       ├── automation/        # Rules engine, smart plugs, overrides
│       ├── species/           # Species profile library
│       ├── vision/            # Frame ingest, local CNN, Claude Vision
│       ├── notifications/     # ntfy push notifications (3-tier)
│       ├── transcript/        # JSON/markdown export, Claude analysis
│       ├── builder/           # Builder's Assistant (Claude API guides)
│       ├── hardware/          # Node registry + commands
│       └── websocket/         # Socket.IO event definitions
├── ui/                        # React 18 + TypeScript + Vite
│   └── src/
│       ├── pages/             # Dashboard, Sessions, Vision, Automation, etc.
│       ├── components/        # Reusable: gauges, charts, timelines
│       ├── stores/            # Zustand stores (telemetry, sessions)
│       ├── api/               # HTTP client + Socket.IO
│       └── constants/         # Shared phases, colors, types
├── config/                    # Mosquitto config
├── docker-compose.yml
└── CLAUDE.md                  # Full system specification
```

## Configuration

All backend settings are configured via environment variables (prefix `SPOREPRINT_`) or a `.env` file in the server directory:

| Variable | Default | Description |
|---|---|---|
| `SPOREPRINT_DATABASE_PATH` | `data/db/sporeprint.db` | SQLite database path |
| `SPOREPRINT_MQTT_HOST` | `localhost` | MQTT broker host |
| `SPOREPRINT_MQTT_PORT` | `1883` | MQTT broker port |
| `SPOREPRINT_NTFY_URL` | `http://localhost:8080` | ntfy server URL |
| `SPOREPRINT_NTFY_TOPIC` | `sporeprint` | ntfy notification topic |
| `SPOREPRINT_VISION_STORAGE` | `data/vision` | Vision frame storage path |
| `SPOREPRINT_CLAUDE_API_KEY` | *(empty)* | Anthropic API key (for vision + builder) |

## Key Features

- **Species Profile Library**: Built-in profiles for 10+ species with per-phase environmental targets. Custom profiles via JSON import.
- **Session Management**: Full grow lifecycle from inoculation through harvest. Phase transitions trigger automation changes.
- **Automation Rules Engine**: Declarative rules — threshold, schedule, or compound conditions trigger actuator commands. Species-aware (references profile targets).
- **Dual Vision Pipeline**: Local CNN for fast contamination detection (~15min cycle), Claude Vision API for deep morphology analysis (~6h cycle).
- **Transcript Export**: Structured JSON + narrative markdown. Includes telemetry summaries, vision analyses, automation logs. Optimized for Claude analysis.
- **Builder's Assistant**: Describe new hardware in natural language, get complete implementation guides (wiring, firmware, MQTT, 3D mounts).
- **Push Notifications**: 3-tier ntfy alerts — critical (immediate), warning (5min dedup), info (hourly batch).

## Development

```bash
# Full check (type check + tests + lint)
cd server && ruff check app/ && pytest
cd ui && npm run check

# Or individually
cd server && pytest                    # Backend tests
cd ui && npm test                      # Frontend tests
cd ui && npm run build                 # Full production build

# Validate Docker Compose
docker compose config --quiet
```

## MQTT Topic Convention

```
sporeprint/{node_id}/telemetry        # Sensor readings (JSON)
sporeprint/{node_id}/status/heartbeat # Node heartbeat
sporeprint/{node_id}/cmd/{channel}    # Actuator commands
shellies/{device_id}/relay/0        # Shelly plug state
tasmota/{device_id}/stat/POWER      # Tasmota plug state
```

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
