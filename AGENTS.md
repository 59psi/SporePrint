# Agents

Specialized agent patterns for working on SporePrint. Use these as context when delegating to sub-agents.

## firmware-agent

**When**: Modifying or adding ESP32 firmware code under `firmware/`.

**Context**: PlatformIO monorepo. Shared libraries in `lib/sporeprint_common/` (WiFi, MQTT, OTA, NVS, heartbeat, offline buffer). Each node type is a build target (`climate_node`, `relay_node`, `lighting_node`, `cam_node`). ESP32-WROOM-32 for most nodes, ESP32-CAM (AI-Thinker) for camera.

**Key constraints**:
- Non-blocking: use `yield()` not `delay()` in loops
- MQTT via PubSubClient, JSON via ArduinoJson v7
- Telemetry payloads must include `ts` (Unix timestamp)
- MQTT topic convention: `sporeprint/{node_id}/telemetry|status|cmd/{channel}`
- PWM: 25kHz, 8-bit for relays, 10-bit for lighting
- NVS for persistent config, SPIFFS ring buffer for offline messages

## backend-agent

**When**: Working on the Python FastAPI backend under `server/app/`.

**Context**: Python 3.11+, FastAPI, aiosqlite (raw SQL, no ORM), aiomqtt, python-socketio, Pydantic v2. No auth — single operator, local network.

**Key constraints**:
- All imports at module top (no inline imports)
- DB access via `async with get_db() as db:` — batch writes in one context + single `commit()`
- Routers are thin — business logic in service modules
- Rule serialization: use `deserialize_rule_row()` / `serialize_rule_data()` from `automation/service.py`
- Vision frame parsing: use `_deserialize_frame()` from `vision/service.py`
- Claude response parsing: use `parse_claude_json()` from `vision/service.py`
- Active session: use `get_active_session()` from `sessions/service.py` — don't duplicate
- Weather providers: subclass `WeatherProvider` in `weather/providers.py`, register in `get_provider()`
- Cloud connector: opt-in via `SPOREPRINT_CLOUD_URL`. No-op when unconfigured. Late import `mqtt_publish` in command handler to avoid circular dep with mqtt.py.
- Health metrics: `psutil` for system stats. `sensors_temperatures()` wrapped in try/except (macOS compat).
- Background tasks (MQTT, weather, retention, retrain, cloud): started in `main.py` lifespan
- Config via `pydantic-settings` with `SPOREPRINT_` env prefix
- Schema defined in `db.py` SCHEMA constant (20 tables)

## frontend-agent

**When**: Working on the React UI under `ui/src/`.

**Context**: React 18 + TypeScript + Vite + Tailwind CSS v4 + Zustand + Socket.IO client + Recharts + React Router v7 + Lucide icons. Dark theme primary.

**Key constraints**:
- Shared constants: `constants/phases.ts` (PHASE_ORDER), `constants/colors.ts` (CATEGORY_COLORS, STATUS_COLORS, HEALTH_COLORS, etc.)
- CSS custom properties for theme: `var(--color-bg-card)`, `var(--color-text-primary)`, `var(--color-accent-gourmet)`, etc.
- API calls via `api/client.ts`, WebSocket via `api/socket.ts`
- Zustand for global state, local useState for component state
- Category accent colors: green=gourmet, amber=medicinal, blue-purple=active
- Icons: Lucide React only

## test-agent

**When**: Writing or running tests.

**Context**:
- Backend: pytest + pytest-asyncio (121 tests). Tests in `server/tests/`. Run with `cd server && pytest`.
- Frontend: vitest (20 tests). Tests in `ui/src/__tests__/`. Run with `cd ui && npm run check` (tsc -b + vitest + eslint).
- Uses temp file SQLite (not `:memory:` — `get_db()` opens new connections). Conftest monkeypatches `settings.database_path`.
- Background tasks (MQTT, weather, retention, retrain) are mocked to no-ops in conftest `client` fixture.

## species-agent

**When**: Adding or modifying species cultivation profiles.

**Context**: 40 species profiles define per-phase environmental targets that drive the entire automation system. Profiles are in `server/app/species/profiles.py`. Changes cascade to automation rules, vision analysis prompts, session defaults, weather impact analysis, and UI display.

**Key constraints**:
- All temperatures in Fahrenheit
- GrowPhase enum: agar, liquid_culture, grain_colonization, substrate_colonization, primordia_induction, fruiting, rest, complete
- Some species have unique automation needs: lion's mane (temp swings), king trumpet (elevated CO2 for pinning), reishi (CO2 controls morphology), cordyceps (blue 450nm light required)
- Profile changes should be reflected in CLAUDE.md section 4b if they differ from the documented values
