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

**Context**: Python 3.11+, FastAPI, aiosqlite (raw SQL, no ORM), aiomqtt, python-socketio, Pydantic v2. Opt-in bearer-token auth via `SPOREPRINT_API_KEY` (v3.3.0+); when unset, the LAN-scoped CORS regex is the only gate — single operator, local network. 17 server modules, 26 SQLite tables, 80+ endpoints across 17 router groups.

**Key constraints**:
- All imports at module top (no inline imports) — including `anthropic` (use `anthropic.AsyncAnthropic` everywhere; never `anthropic.Anthropic`)
- DB access via `async with get_db() as db:` — batch writes in one context + single `commit()`. Every connection automatically gets `PRAGMA foreign_keys=ON` + `busy_timeout=5000` via `_apply_connection_pragmas`.
- Routers are thin — business logic in service modules
- Rule serialization: use `deserialize_rule_row()` / `serialize_rule_data()` from `automation/service.py`
- Vision frame parsing: use `_deserialize_frame()` from `vision/service.py`
- Claude response parsing: use `parse_claude_json()` from `vision/service.py`
- Active session: use `get_active_session()` from `sessions/service.py` — don't duplicate
- Weather providers: subclass `WeatherProvider` in `weather/providers.py`, register in `get_provider()`
- Cloud connector: opt-in via `SPOREPRINT_CLOUD_URL`. No-op when unconfigured. Late import `mqtt_publish` in command handler to avoid circular dep with mqtt.py.
- MQTT broker: `allow_anonymous false` in production. `settings.mqtt_username`/`mqtt_password` flow into `aiomqtt.Client(...)`. Firmware reads `mqtt_user`/`mqtt_pass` from NVS. Server user needs topic-write permission on `cmd/#`; per-node users only get their own namespace (see `config/mosquitto/acl.conf`).
- Bearer-token gate: `app/auth.py` `ApiKeyMiddleware` guards all `/api/*` + Socket.IO `connect`. Whitelist: `/api/health`, `/api/cloud/pair`, `/api/cloud/pairing-code`. Never add a new `/api/*` route that bypasses this without explicit justification.
- Automation rule-fire ordering: INSERT `automation_firings` with `status='pending'` → `mqtt_publish` (returns bool) → UPDATE `status='sent'|'failed'`. Never write `status='sent'` before confirming the publish landed.
- Manual overrides: source of truth is the `manual_overrides` table. Call `await ensure_overrides_loaded()` before reading the in-memory cache; use `set_override`/`clear_override` (both async now) for writes.
- Timestamp clamp: any `ts < 1577836800` (2020-01-01) in incoming telemetry is firmware uptime-seconds — clamp to `time.time()` in `mqtt._handle_message`. Do not relax this.
- Retention rollups: use `INSERT ... ON CONFLICT DO UPDATE` with weighted-mean merging, never `INSERT OR IGNORE + DELETE`.
- Health metrics: `psutil` for system stats. `sensors_temperatures()` wrapped in try/except (macOS compat). Reliability counters (`uptime_ts_clamps`, `mqtt_supervisor_restarts`) surface on `/api/health/detail/system.reliability`.
- Background tasks (MQTT, weather, retention, retrain, cloud, weather_history aggregation, node-liveness sweeper): started in `main.py` lifespan
- Config via `pydantic-settings` with `SPOREPRINT_` env prefix
- Schema defined in `db.py` SCHEMA constant (26 tables) + migrations via `_add_column_if_missing`
- New v3.0 modules (planner/, contamination/, cultures/, chambers/, experiments/, labels/) follow same patterns: models.py, service.py, router.py
- Additional dependencies: qrcode[pil], icalendar, matplotlib, `python-multipart>=0.0.18` (CVE-2024-24762)

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
- Backend: pytest + pytest-asyncio (256 tests as of v3.3.0). Tests in `server/tests/`. Run with `cd server && pytest`.
- Frontend: vitest (20 tests). Tests in `ui/src/__tests__/`. Run with `cd ui && npm run check` (tsc -b + vitest + eslint).
- Uses temp file SQLite (not `:memory:` — `get_db()` opens new connections). Conftest monkeypatches `settings.database_path`. FK constraints are live, so tests that insert child rows must first insert the parent (see `test_store_reading_with_session_id`).
- Background tasks (MQTT, weather, retention, retrain, node-liveness sweeper) are mocked to no-ops in conftest `client` fixture.
- `mock_mqtt` fixture returns a calls-list with a `.mock` attribute; set `mock_mqtt.mock.return_value = False` to simulate a broker-down state mid-publish.

## species-agent

**When**: Adding or modifying species cultivation profiles.

**Context**: 55 species profiles (19 active, 24 gourmet, 7 medicinal, 5 novelty) define per-phase environmental targets that drive the entire automation system. Profiles are in `server/app/species/profiles.py`. Changes cascade to automation rules, vision analysis prompts, session defaults, weather impact analysis, and UI display. Each profile now includes TEK guides, substrate recipes, contamination risks, photo references, and regional notes.

**Key constraints**:
- All temperatures in Fahrenheit
- GrowPhase enum: agar, liquid_culture, grain_colonization, substrate_colonization, primordia_induction, fruiting, rest, complete
- Some species have unique automation needs: lion's mane (temp swings), king trumpet (elevated CO2 for pinning), reishi (CO2 controls morphology), cordyceps (blue 450nm light required)
- Profile changes should be reflected in CLAUDE.md section 4b if they differ from the documented values
