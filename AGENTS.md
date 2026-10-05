# Agents

Specialized agent patterns for working on SporePrint. Use these as context when delegating to sub-agents.

## firmware-agent

**When**: Modifying or adding ESP32 firmware code under `firmware/`.

**Context**: PlatformIO monorepo (v2). Native-safe libraries `lib/sp_core` (HMAC canonicalizer + replay guard, channel state machine, buffers, boot / TLS / publish-cadence policy) + `lib/sp_drivers` (sensors over injected HAL) are host-tested via `pio test -e native`; `lib/sp_device` is the Arduino layer (portal, MQTT link, OTA + rollback, TLS, NVS). Two images: the unified node (`node_esp32` for the WROOM-32, `node_esp32s3` for S3 N8/N8R8/N16R8, `node_esp32s3_n32r16v` for the S3 N32R16V — personality picked at provisioning) and the camera (`cam`, AI-Thinker, OV2640 / OV3660 / OV5640 auto-detected). Board pin maps live in `boards/` (the S3 map differs from the WROOM-32's). Shared build settings live in the `[esp32_base]` section of `platformio.ini` (there is no `[env]` base).

**Key constraints**:
- Non-blocking: use `yield()` not `delay()` in loops
- MQTT via PubSubClient 2.8, JSON via ArduinoJson 7.4.3 (exact pins)
- Telemetry `ts` is Unix-epoch seconds once NTP has synced and uptime seconds before that; the Pi treats `ts < 1e9` as unsynced. Frames replayed from the offline buffer carry `"replay": true`
- MQTT topic convention: `sporeprint/{node_id}/telemetry|status|health|alert|logs|cmd/{channel}`; the heartbeat (`status/heartbeat`) goes out every min(publish interval, 5 min)
- PWM: 25 kHz, 10-bit LEDC on every channel (relay and lighting banks)
- NVS for persistent config; the offline telemetry buffer is a 16 KB byte-capped RAM FIFO
- Wire contract is additive only: new payload keys optional, `firmware/test/fixtures/signing_vectors.json` byte-identical to `server/tests/fixtures/signing_vectors.json`
- Any GPIO change must update every wiring diagram (tier SVGs via `scripts/wiring_svg/build.py`), the BOM (`server/app/builder/hardware_guides.py`) and `docs/hardware-build-guide.md` in the same change, then refresh the dashboard's built-in Builder data (rebuild `ui/dist`, or `scripts/sync_ui_builder_data.py`)

## backend-agent

**When**: Working on the Python FastAPI backend under `server/app/`.

**Context**: Python 3.11+, FastAPI, aiosqlite (raw SQL, no ORM), aiomqtt, python-socketio, Pydantic v2. Opt-in bearer-token auth via `SPOREPRINT_API_KEY` (v3.3.0+); the default install is LAN-trust (`SPOREPRINT_ALLOW_UNAUTHENTICATED=true`) because the bundled dashboard sends no bearer. 20 server modules, 33 SQLite tables, 150 API operations.

**Key constraints**:
- All imports at module top (no inline imports) — including `anthropic` (use `anthropic.AsyncAnthropic` everywhere; never `anthropic.Anthropic`)
- Claude calls use `settings.claude_model` (never a literal model id); read text with `vision/service.py`'s `claude_response_text()` and parse JSON with `parse_claude_json()` (never raises)
- DB access via `async with get_db() as db:` — batch writes in one context + single `commit()`. Every connection automatically gets `PRAGMA foreign_keys=ON` + `busy_timeout=5000` via `_apply_connection_pragmas`.
- Routers are thin — business logic in service modules
- Rule serialization: use `deserialize_rule_row()` / `serialize_rule_data()` from `automation/service.py`; OFF payloads go through `drop_duty_from_off()` / `is_off_command()` there
- Vision frame parsing: use `_deserialize_frame()` from `vision/service.py`
- Active session: `get_active_session()` for the single-closet case; per node, `get_active_session_for_node()` / `get_active_session_for_chambers()` in `sessions/service.py` (with `chambers.service.chambers_for_node()`) — don't write another per-node session query
- Phase validation: `phase_error()`, `InvalidPhaseError`, `PHASE_PARAM_FALLBACKS` live in `sessions/service.py`
- Weather providers: subclass `WeatherProvider` in `weather/providers.py`, register in `get_provider()`
- Cloud connector: opt-in via `SPOREPRINT_CLOUD_URL`, or pairing credentials persisted to `cloud.env` beside the DB. No-op when unconfigured.
- MQTT broker: `allow_anonymous false`. `settings.mqtt_username`/`mqtt_password` flow into `aiomqtt.Client(...)`. Each node's broker username equals its node id (`scripts/add-node-mqtt-user.sh`); the ACL (`config/mosquitto/acl.conf`) scopes it to `sporeprint/<node_id>/…`. The server user needs write on `cmd/#`; smart plugs use `sp-3p` (`tasmota/#`, `shellies/#`).
- Command signing: `mqtt_publish` signs every `cmd/*` frame with `SPOREPRINT_MQTT_HMAC_KEY` and binds `topic` + `nonce`; `SPOREPRINT_MQTT_REQUIRE_SIGNING` (`auto`/`always`/`never`) decides what happens with no key
- Bearer-token gate: `app/auth.py` `ApiKeyMiddleware` guards all `/api/*` + Socket.IO `connect`. Public: `/api/health`, `POST /api/cloud/pair`, `GET /api/provision/ca`; `POST /api/vision/frame` keyless only for a registered camera. Never add a new `/api/*` route that bypasses this without explicit justification.
- Automation rule-fire ordering: INSERT `automation_firings` with `status='pending'` → `mqtt_publish` (returns bool) → UPDATE `status='sent'|'failed'`. Never write `status='sent'` before confirming the publish landed.
- Every non-automation OFF that was published calls `automation.engine.note_actuator_off()` (sessions registers it via `sessions.service.add_actuator_off_listener()`; sessions must not import the engine)
- Import cycles: `app.sessions.service` imports `app.mqtt`, `app.automation.service`, `app.automation.smart_plugs` and `app.notifications.service` at module top, so none of those (or anything they import at top level) may import `app.sessions.service` at module level; `automation/engine.py` imports `app.integrations._actions`, so integrations and smart_plugs must not import the engine
- Manual overrides: source of truth is the `manual_overrides` table. Call `await ensure_overrides_loaded()` before reading the in-memory cache; use `set_override`/`clear_override` (both async) for writes.
- Telemetry timestamps: `ts < 1e9` is firmware uptime — stamp arrival time. Replayed (`"replay": true`) or synced frames older than 120 s are stored at their own time but never evaluated by rules or pushed live.
- Retention rollups: use `INSERT ... ON CONFLICT DO UPDATE` with count-weighted merging, never `INSERT OR IGNORE + DELETE`.
- Health metrics: `psutil` for system stats. `sensors_temperatures()` wrapped in try/except (macOS compat). Reliability counters (`uptime_ts_clamps`, `mqtt_supervisor_restarts`) surface on `/api/health/detail/system.reliability`.
- Background tasks (MQTT, weather, retention, retrain, cloud, weather_history aggregation, node-liveness sweeper, phase reminders): started in `main.py` lifespan
- Config via `pydantic-settings` with `SPOREPRINT_` env prefix; every new `Settings` field must also be forwarded in `docker-compose.yml` (`tests/test_docker.py` enforces it)
- Schema defined in `db.py` SCHEMA constant (33 tables) + migrations via `_add_column_if_missing`
- v3.0+ modules (planner/, contamination/, cultures/, chambers/, experiments/, labels/) follow the same pattern: models.py, service.py, router.py
- Dependencies are locked in `server/uv.lock` (the Docker image installs exactly those, hash-checked); after changing `pyproject.toml` run `uv lock`
- Hardware BOM (`builder/hardware_guides.py`): cabling and consumables are real BOM lines (categories `wiring` / `hardware`); `shared=True` marks per-installation lines (the Pi side, the bench breadboard) that the Builder's chamber count does not multiply; anything the chambers use up — kits, spools, zip ties, heat-shrink, grommets — is a per-chamber pack line (`quantity` per chamber, `pack_size`, `shared_units` for the Pi case's share of the same pack — insert/screw counts from the `models/README.md` shopping list — and `unit` when it counts feet, grams or one piece of a mixed kit rather than pieces of the part). A BOM change updates the README tier table, `docs/hardware-build-guide.md` (§0 prices + second-chamber row, §7 cabling) and the wiring SVGs in the same change (the three tier SVGs are generated: edit `scripts/wiring_svg/gen_t*.py` / `parts.py` and run `python3 scripts/wiring_svg/build.py` — `tests/test_wiring_svgs_generated.py` rejects hand edits), and refreshes the dashboard's built-in Builder data (rebuild `ui/dist`, or `scripts/sync_ui_builder_data.py`). `tests/test_docs_consistency.py` and `tests/test_ui_builder_sync.py` enforce both

## frontend-agent

**When**: Working on the React UI. The source lives in the parent monorepo (`frontend/packages/pi-ui`); this repo ships only the pre-built bundle in `ui/dist`, served by the `ui` nginx container (`ui/nginx.conf` proxies `/api` and `/socket.io`). The bundle's Builder page reads the server live: `/api/builder/tiers` (plus `/tiers/{id}`), `/models`, `/diagrams` and `/firmware`. When a request fails, that resource falls back to a copy built into the bundle. The monorepo's `scripts/port_builder.py` generates that copy from this repo into `design/src/data/builder.generated.ts`. To rebuild, run from the monorepo root: `python3 scripts/port_builder.py --public-repo <this repo>`, then `pnpm -C frontend --filter @sporeprint/pi-ui build`, then `rsync -a --delete --checksum frontend/packages/pi-ui/dist/ <this repo>/ui/dist/`. `scripts/sync_ui_builder_data.py --check` (run from `server/` with `uv run python ../scripts/...`) verifies the bundle against the server: that it reads the API live and that its built-in tiers, models, diagrams and firmware envs match. Without `--check`, the script rewrites stale built-in data in place. It never patches code.

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
- Backend: pytest + pytest-asyncio. Tests in `server/tests/`. Run with `cd server && pytest`.
- Firmware: host-native Unity suites in `firmware/test/` (see `firmware/test/README.md`). Run with `cd firmware && pio test -e native`; build every image with `pio run -e node_esp32 -e node_esp32s3 -e node_esp32s3_n32r16v -e cam`.
- Uses temp file SQLite (not `:memory:` — `get_db()` opens new connections). Conftest monkeypatches `settings.database_path`. FK constraints are live, so tests that insert child rows must first insert the parent (see `test_store_reading_with_session_id`).
- Background tasks (MQTT, weather, retention, retrain, node-liveness sweeper) are mocked to no-ops in conftest `client` fixture.
- `mock_mqtt` fixture returns a calls-list with a `.mock` attribute; set `mock_mqtt.mock.return_value = False` to simulate a broker-down state mid-publish.
- `tests/test_docs_consistency.py` pins the docs (README, build guide, SVGs, AGENTS.md) to the code, firmware and BOM — update the docs with the code. `tests/test_ui_builder_sync.py` fails when `ui/dist`'s Builder page stops reading `/api/builder/*` live, or when its built-in fallback differs from the server.

## species-agent

**When**: Adding or modifying species cultivation profiles.

**Context**: 74 built-in species profiles (30 gourmet, 25 active, 11 medicinal, 8 novelty) define per-phase environmental targets that drive the entire automation system. Profiles are in `server/app/species/profiles.py`. Changes cascade to automation rules, vision analysis prompts, session defaults, weather impact analysis, and UI display. Each profile includes TEK guides, substrate recipes, contamination risks, photo references, and regional notes.

**Key constraints**:
- All temperatures in Fahrenheit
- GrowPhase enum: agar, liquid_culture, grain_colonization, substrate_colonization, cold_storage, primordia_induction, fruiting, rest, complete
- Phases a profile lacks: primordia_induction ↔ fruiting and rest → fruiting borrow setpoints (`PHASE_PARAM_FALLBACKS`); a profile with neither fruiting nor primordia setpoints refuses those phases (422)
- Built-ins are read-only (PUT returns 409 — clone to customize)
- Some species have unique automation needs: lion's mane (temp swings), king trumpet (elevated CO2 for pinning), reishi (CO2 controls morphology), cordyceps (blue 450nm light required)
- Profile changes should be reflected in CLAUDE.md section 4b if they differ from the documented values
