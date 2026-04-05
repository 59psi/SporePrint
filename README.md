# SporePrint

Automated mushroom cultivation system for a single grow closet. Supports 40 species across gourmet, medicinal, and active categories with full environmental automation, weather-predictive intelligence, dual vision pipeline, and Claude-powered analysis.

## Architecture

```
ESP32 Nodes ──MQTT──▶ Raspberry Pi Backend ◀──REST/WS──▶ React UI
  (sensors,            (FastAPI, SQLite,                  (dashboard,
   relays,              automation engine,                 sessions,
   lighting,            weather prediction,                vision,
   camera)              ntfy notifications)                transcripts)
```

**Hardware layer**: ESP32 sensor/actuator nodes (climate, relay/SSR, lighting, camera) + Shelly/Tasmota smart plugs, all communicating via MQTT. 3-tier hardware builder with shopping lists and wiring diagrams.

**Backend**: FastAPI on Raspberry Pi 4/5. SQLite with tiered retention (~120 MB/year). Mosquitto MQTT broker. Declarative automation rules engine with weather-aware virtual sensors. Dual vision pipeline (local CNN + Claude API). Predictive model learns weather-to-closet correlation. ntfy push notifications up to 72h in advance.

**Frontend**: React 18 + TypeScript + Vite + Tailwind. Real-time WebSocket updates. 7-day forecast with grow impact analysis. PWA-capable. Dark theme.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose (for deployment)
- PlatformIO (for firmware, optional)

### Setup Script (recommended)

```bash
git clone <repo-url> && cd SporePrint
./setup.sh
```

The setup script checks prerequisites, creates `.env` from the template, prompts for API keys, installs all dependencies, and prints next steps.

### Manual Development Setup

```bash
cd server && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Edit with your settings
uvicorn app.main:socket_app --reload

# Frontend (separate terminal)
cd ui && npm install && npm run dev

# MQTT broker (separate terminal, or use Docker)
docker run -d -p 1883:1883 -p 9001:9001 eclipse-mosquitto:2
```

UI at `http://localhost:3001`, API at `http://localhost:8000`.

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
│   ├── lib/sporeprint_common/ # Shared: WiFi, MQTT, OTA, heartbeat, offline buffer
│   └── src/
│       ├── climate_node/      # SHT31, SCD40, BH1750 sensors
│       ├── relay_node/        # IRLZ44N SSR control (4ch PWM)
│       ├── lighting_node/     # Multi-channel LED (white, blue, red, far-red)
│       └── cam_node/          # ESP32-CAM MJPEG + frame POST
├── server/                    # Python FastAPI backend
│   ├── tests/                 # pytest + pytest-asyncio (121 tests)
│   └── app/
│       ├── main.py            # App entrypoint + Socket.IO + background tasks
│       ├── config.py          # Pydantic settings (env vars)
│       ├── db.py              # SQLite schema (20 tables) + connection manager
│       ├── mqtt.py            # MQTT subscriber + weather enrichment
│       ├── telemetry/         # Sensor data ingest + rollup-aware history
│       ├── sessions/          # Grow session lifecycle + location tracking
│       ├── automation/        # Rules engine, smart plugs, overrides
│       ├── species/           # 40 species profiles
│       ├── vision/            # Frame ingest, local CNN, Claude Vision
│       ├── weather/           # Multi-provider weather, prediction, forecasts
│       ├── retention/         # Tiered data compression (raw → 5min → hourly → daily)
│       ├── notifications/     # ntfy push notifications (3-tier + predictive)
│       ├── transcript/        # JSON/markdown export, Claude analysis
│       ├── builder/           # 3-tier hardware guide + Claude assistant
│       ├── hardware/          # Node registry + commands
│       └── websocket/         # Socket.IO event definitions
├── ui/                        # React 18 + TypeScript + Vite
│   └── src/
│       ├── pages/             # Dashboard, Sessions, Vision, Automation, etc.
│       ├── components/        # Gauges, charts, timelines, wiring diagrams
│       ├── stores/            # Zustand stores (telemetry, sessions)
│       ├── api/               # HTTP client + Socket.IO
│       ├── constants/         # Shared phases, colors
│       └── __tests__/         # vitest (20 tests)
├── config/                    # Mosquitto config
├── docker-compose.yml
└── CLAUDE.md                  # Full system specification
```

## Configuration

All settings via environment variables (prefix `SPOREPRINT_`) or `.env` file:

| Variable | Default | Description |
|---|---|---|
| `SPOREPRINT_DATABASE_PATH` | `data/db/sporeprint.db` | SQLite database path |
| `SPOREPRINT_MQTT_HOST` | `localhost` | MQTT broker host |
| `SPOREPRINT_MQTT_PORT` | `1883` | MQTT broker port |
| `SPOREPRINT_NTFY_URL` | `http://localhost:8080` | ntfy server URL |
| `SPOREPRINT_NTFY_TOPIC` | `sporeprint` | ntfy notification topic |
| `SPOREPRINT_VISION_STORAGE` | `data/vision` | Vision frame storage path |
| `SPOREPRINT_CLAUDE_API_KEY` | *(empty)* | Anthropic API key (vision + builder assistant) |
| `SPOREPRINT_WEATHER_PROVIDER` | `openmeteo` | `openmeteo` (free, no key), `openweathermap` (needs key), `nws` (US-only, free) |
| `SPOREPRINT_WEATHER_API_KEY` | *(empty)* | Only needed for OpenWeatherMap |
| `SPOREPRINT_WEATHER_LAT` | *(empty)* | Latitude for weather data |
| `SPOREPRINT_WEATHER_LON` | *(empty)* | Longitude for weather data |
| `SPOREPRINT_WEATHER_POLL_MINUTES` | `10` | Weather polling interval |

## Key Features

- **40 Species Profiles**: Gourmet (24), medicinal (6), active (10). Per-phase environmental targets for temperature, humidity, CO2, light, FAE. Custom profiles via JSON import.
- **Session Management**: Full grow lifecycle with location tracking (tub number, shelf, side). Phase transitions trigger automation changes.
- **Automation Rules Engine**: Declarative rules with threshold, schedule, and compound conditions. Species-aware (references profile targets). Weather-aware virtual sensors.
- **Weather-Predictive Intelligence**: 3 providers (Open-Meteo, OpenWeatherMap, NWS). 7-day forecast on dashboard. Learns weather-to-closet correlation over time. Predicts indoor conditions and alerts up to 72h in advance when species targets will be violated.
- **Data Retention**: Tiered compression — raw (7 days) → 5-min averages (30 days) → hourly (1 year) → daily (forever). ~120 MB/year on Raspberry Pi.
- **Dual Vision Pipeline**: Local CNN for fast contamination detection (~15min cycle), Claude Vision API for deep morphology analysis.
- **3-Tier Hardware Builder**: Pre-built shopping lists with purchase links, color-coded SVG wiring diagrams, and step-by-step setup instructions. Bare Bones (~$100), Recommended (~$200), All the Things (~$350+). Claude assistant for custom questions.
- **Transcript Export**: Structured JSON + narrative markdown with telemetry summaries, vision analyses, automation logs. Claude analysis with scoring.
- **Push Notifications**: 3-tier ntfy alerts — critical (immediate), warning (5min dedup), info (hourly batch). Weather-predictive alerts up to 72h out.

## Development

```bash
# Full check (type check + tests + lint)
cd server && ruff check app/ && pytest
cd ui && npm run check

# Or individually
cd server && pytest                    # 121 backend tests
cd ui && npm test                      # 20 frontend tests
cd ui && npm run build                 # Full production build

# Validate Docker Compose
docker compose config --quiet
```

## MQTT Topic Convention

```
sporeprint/{node_id}/telemetry        # Sensor readings (JSON)
sporeprint/{node_id}/status/heartbeat # Node heartbeat
sporeprint/{node_id}/cmd/{channel}    # Actuator commands
shellies/{device_id}/relay/0          # Shelly plug state
tasmota/{device_id}/stat/POWER        # Tasmota plug state
```

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
