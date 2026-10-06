# Agents

Specialized agent patterns for working on SporePrint. Use these as context when delegating to sub-agents.

## firmware-agent

**When**: Modifying or adding ESP32 firmware code under `firmware/`.

**Context**: PlatformIO monorepo (v2). Native-safe libraries `lib/sp_core` (HMAC canonicalizer + replay guard, channel state machine, buffers, boot / TLS / publish-cadence policy) + `lib/sp_drivers` (sensors over injected HAL) are host-tested via `pio test -e native`; `lib/sp_device` is the Arduino layer (portal, MQTT link, OTA + rollback, TLS, NVS). Two images: the unified node (`node_esp32` for the WROOM-32, `node_esp32s3` for S3 N8/N8R8/N16R8, `node_esp32s3_n32r16v` for the S3 N32R16V — personality picked at provisioning) and the camera (`cam`, AI-Thinker, OV2640 / OV3660 / OV5640 auto-detected; the same image also builds as `cam_esp32s3` / `cam_xiao_esp32s3` / `cam_waveshare_s3` for the ESP32-S3 camera boards earlier BOMs listed, pin maps in `boards/board_profile_esp32s3cam.h`). Board pin maps live in `boards/` (the S3 map differs from the WROOM-32's). Shared build settings live in the `[esp32_base]` section of `platformio.ini` (there is no `[env]` base). Platform: pioarduino release `55.03.312-1` = Arduino-ESP32 core 3.3.12 on ESP-IDF 5.5.5, pinned by its immutable release URL (needs PlatformIO Core ≥ 6.2.0 and git); every source builds at the framework's C++20 dialect and the native env at `-std=gnu++20`. `scripts/image_guard.py` runs after every build and fails it on a partition table that differs from the fleet layout, < 64 KiB free in the OTA slot, linked ESP-Matter code, or the Arduino LEDC allocator in a cam image. Driver inventory: `docs/drivers.md`.

**Key constraints**:
- Non-blocking: use `yield()` not `delay()` in loops
- MQTT via PubSubClient 2.8, JSON via ArduinoJson 7.4.3 (exact pins)
- Telemetry `ts` is Unix-epoch seconds once NTP has synced and uptime seconds before that; the Pi treats `ts < 1e9` as unsynced. Frames replayed from the offline buffer carry `"replay": true`
- MQTT topic convention: `sporeprint/{node_id}/telemetry|status|health|alert|logs|cmd/{channel}`; the heartbeat (`status/heartbeat`) goes out every min(publish interval, 5 min)
- Coredumps are store-then-ack: chunks on `coredump/chunk` carry `coredump_id` (SHA-256 of the dump), the Pi answers `cmd/coredump_ack {coredump_id}` only once the file is durably on disk, and the node erases its flash copy only on that ack (bounded retries, else kept; `sp_core/coredump_drain.h`, `server/app/hardware/coredumps.py`)
- Signed node OTA (`sp_core/ota_manifest.h` + `ota_gate.h`): `cmd/ota_manifest {manifest_b64, sig_b64}` arms the next push to the manifest's sha256/size when the image was built with `SPOREPRINT_OTA_PUBKEY_B64`; the key is a build input (`scripts/fw_version.py`), never NVS-over-MQTT
- PWM: 25 kHz, 10-bit LEDC on every channel (relay and lighting banks), bound by pin with `ledcAttachChannel(pin, 25000, 10, i)`; relay commands carry `pwm` 0-255 on the wire, lighting `level` 0-1023
- Network OTA is `sp_device/ota_service.cpp` speaking the core-2.x espota MD5 handshake (`sp_core/espota.h`) on port 3232, because every Pi before 2026-10 answers only that one; core 3.x's stock `ArduinoOTA` accepts only PBKDF2. The Pi's push (`server/app/hardware/ota_push.py`) now answers both, chosen by nonce length (32 hex = MD5, 64 = PBKDF2-SHA256), so a firmware may move to the stock library once the Pis it must accept pushes from run this release or later
- Core-3 pitfalls already handled: the task WDT is reconfigured, never re-initialised (`sp_device/task_wdt.h`); DNS is capped at 15 s (`sp_device/bounded_dns.h`); connects use `setConnectionTimeout()` (on 3.x `setTimeout()` no longer bounds a connect); the default node id comes from `esp_read_mac()`
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
- MQTT broker: `allow_anonymous false`. `settings.mqtt_username`/`mqtt_password` flow into `aiomqtt.Client(...)`. Each node's broker username equals its node id (`scripts/add-node-mqtt-user.sh`); the ACL (`config/mosquitto/acl.conf`) scopes it to `sporeprint/<node_id>/…`. The server user needs write on `cmd/#`; smart plugs use `sp-3p` (`tasmota/#`, `shellies/#`). Shelly Gen2+ plugs (`plug_type` `shelly_gen2`, JSON-RPC) must use MQTT prefix `shellies/<role>` — the ACL grants the server only `shellies/+/rpc` — and `automation/smart_plugs.py` refuses any other prefix rather than publish into a dropped topic.
- Command signing: `mqtt_publish` signs every `cmd/*` frame with `SPOREPRINT_MQTT_HMAC_KEY` and binds `topic` + `nonce`; `SPOREPRINT_MQTT_REQUIRE_SIGNING` (`auto`/`always`/`never`) decides what happens with no key
- Bearer-token gate: `app/auth.py` `ApiKeyMiddleware` guards all `/api/*` + Socket.IO `connect`. Public: `/api/health`, `POST /api/cloud/pair`, `GET /api/provision/ca`; `POST /api/vision/frame` keyless only for a registered camera. Never add a new `/api/*` route that bypasses this without explicit justification.
- Coredumps (`hardware/coredumps.py`): `ingest_chunk` stores the reassembled dump durably (temp file, fsync, rename) and only then does `mqtt.py` publish `cmd/coredump_ack {coredump_id}`; never ack before the file is on disk
- OTA signing: the Pi self-update verifies `{version}.manifest.json` + `.sig` with `cloud/ota_manifest.py` against the locally pinned key only (never a key from the OTA command); node pushes can carry the same manifest format, checked by `hardware/node_manifest.py`
- Automation rule-fire ordering: INSERT `automation_firings` with `status='pending'` → `mqtt_publish` (returns bool) → UPDATE `status='sent'|'failed'`. Never write `status='sent'` before confirming the publish landed.
- Every non-automation OFF that was published calls `automation.engine.note_actuator_off()` (sessions registers it via `sessions.service.add_actuator_off_listener()`; sessions must not import the engine)
- Import cycles: `app.sessions.service` imports `app.mqtt`, `app.automation.service`, `app.automation.smart_plugs` and `app.notifications.service` at module top, so none of those (or anything they import at top level) may import `app.sessions.service` at module level; `automation/engine.py` imports `app.integrations._actions`, so integrations and smart_plugs must not import the engine
- Manual overrides: source of truth is the `manual_overrides` table. Call `await ensure_overrides_loaded()` before reading the in-memory cache; use `set_override`/`clear_override` (both async) for writes.
- Telemetry timestamps: `ts < 1e9` is firmware uptime — stamp arrival time. Replayed (`"replay": true`) frames and out-of-order frames (older than the node's newest live `ts`, by at most 120 s) are stored at their own time but never evaluated by rules or pushed live. A frame more than 120 s behind the node's newest `ts` is a clock step-back: it re-baselines the node and stays live. The Pi's own clock never decides liveness (`mqtt.py` `_classify_frame`).
- Retention rollups: use `INSERT ... ON CONFLICT DO UPDATE` with count-weighted merging, never `INSERT OR IGNORE + DELETE`.
- Health metrics: `psutil` for system stats. `sensors_temperatures()` wrapped in try/except (macOS compat). Reliability counters (`uptime_ts_clamps`, `mqtt_supervisor_restarts`) surface on `/api/health/detail/system.reliability`.
- Background tasks (MQTT, weather, retention, retrain, cloud, weather_history aggregation, node-liveness sweeper, phase reminders): started in `main.py` lifespan
- Config via `pydantic-settings` with `SPOREPRINT_` env prefix; every new `Settings` field must also be forwarded in `docker-compose.yml` (`tests/test_docker.py` enforces it)
- Schema defined in `db.py` SCHEMA constant (33 tables) + migrations via `_add_column_if_missing`
- v3.0+ modules (planner/, contamination/, cultures/, chambers/, experiments/) follow the same pattern: models.py, service.py, router.py. labels/ is router-only (one QR endpoint, no models or service)
- Dependencies are locked in `server/uv.lock` (the Docker image installs exactly those, hash-checked); after changing `pyproject.toml` run `uv lock`
- Hardware BOM (`builder/hardware_guides.py`): cabling and consumables are real BOM lines (categories `wiring` / `hardware`); `shared=True` marks per-installation lines (the Pi side, the bench breadboard) that the Builder's chamber count does not multiply; anything the chambers use up — kits, spools, zip ties, heat-shrink, grommets — is a per-chamber pack line (`quantity` per chamber, `pack_size`, `shared_units` for the Pi case's share of the same pack — insert/screw counts from the `models/README.md` shopping list — and `unit` when it counts feet, grams or one piece of a mixed kit rather than pieces of the part). A BOM change updates the README tier table, `docs/hardware-build-guide.md` (§0 prices + second-chamber row, §7 cabling) and the wiring SVGs in the same change (the three tier SVGs are generated: edit `scripts/wiring_svg/gen_t*.py` / `parts.py` and run `python3 scripts/wiring_svg/build.py` — `tests/test_wiring_svgs_generated.py` rejects hand edits), and refreshes the dashboard's built-in Builder data (rebuild `ui/dist`, or `scripts/sync_ui_builder_data.py`). `tests/test_docs_consistency.py` and `tests/test_ui_builder_sync.py` enforce both

## frontend-agent

**When**: Working on the React UI. The source lives in the parent monorepo (`frontend/packages/pi-ui`); this repo ships only the pre-built bundle in `ui/dist`, served by the `ui` nginx container (`ui/nginx.conf` proxies `/api` and `/socket.io`). The bundle's Builder page reads the server live: `/api/builder/tiers` (plus `/tiers/{id}`), `/models`, `/diagrams` and `/firmware`. When a request fails, that resource falls back to a copy built into the bundle. The monorepo's `scripts/port_builder.py` generates that copy from this repo into `design/src/data/builder.generated.ts`. To rebuild, run from the monorepo root: `python3 scripts/port_builder.py --public-repo <this repo>`, then `pnpm -C frontend --filter @sporeprint/pi-ui build`, then `rsync -a --delete --checksum frontend/packages/pi-ui/dist/ <this repo>/ui/dist/`. `scripts/sync_ui_builder_data.py --check` (run from `server/` with `uv run python ../scripts/...`) verifies the bundle against the server: that it reads the API live and that its built-in tiers, models, diagrams and firmware envs match. Without `--check`, the script rewrites stale built-in data in place. It never patches code.

**Context**: React 19 + TypeScript + Vite 6 + Tailwind CSS v4 + React Router v7 + Lucide icons, on the shared `@sporeprint/design` package (tokens, Radix-based components, Recharts, TanStack Table); tests with Vitest. Dark theme primary. No Zustand and no Socket.IO client: pages load over REST, and the Chambers page polls system metrics every 15 s.

**Key constraints**:
- Shared constants: phase helpers in `pi-ui/src/lib/phases.ts`, typed over `GrowPhase` from `src/lib/pi-enums.ts` (generated from this repo's enum by the monorepo's `scripts/port_enums.py`, so a new phase fails typecheck until mapped); `CATEGORY_COLORS` from `@sporeprint/design`
- CSS custom properties for theme: `var(--bg-1)`, `var(--text-0)`, `var(--accent)`, `var(--cat-gourmet)`, etc.
- API calls via `lib/api.ts` (`apiGet` / `apiSend`), page loads via `lib/use-pi-load.ts`
- React state per page; no global store
- Category accent colors: green=gourmet, amber=medicinal, blue-violet=active, orchid=novelty (`--cat-*`)
- Icons: Lucide React only

## test-agent

**When**: Writing or running tests.

**Context**:
- Backend: pytest + pytest-asyncio. Tests in `server/tests/`. Run with `cd server && pytest`.
- Firmware: host-native Unity suites in `firmware/test/` (see `firmware/test/README.md`). Run with `cd firmware && pio test -e native`; build every image with `pio run -e node_esp32 -e node_esp32s3 -e node_esp32s3_n32r16v -e cam -e cam_esp32s3 -e cam_xiao_esp32s3 -e cam_waveshare_s3`.
- Uses temp file SQLite (not `:memory:` — `get_db()` opens new connections). Conftest monkeypatches `settings.database_path`. FK constraints are live, so tests that insert child rows must first insert the parent (see `test_store_reading_with_session_id`).
- Background tasks (MQTT, weather, retention, retrain, node-liveness sweeper) are mocked to no-ops in conftest `client` fixture.
- `mock_mqtt` fixture returns a calls-list with a `.mock` attribute; set `mock_mqtt.mock.return_value = False` to simulate a broker-down state mid-publish.
- `tests/test_docs_consistency.py` pins the docs (README, build guide, SVGs, AGENTS.md) to the code, firmware and BOM — update the docs with the code. `tests/test_ui_builder_sync.py` fails when `ui/dist`'s Builder page stops reading `/api/builder/*` live, or when its built-in fallback differs from the server.

## species-agent

**When**: Adding or modifying species cultivation profiles.

**Context**: 74 built-in species profiles (30 gourmet, 25 active, 11 medicinal, 8 novelty) define per-phase environmental targets that drive the entire automation system. Profiles are in `server/app/species/profiles.py`. Changes cascade to automation rules, vision analysis prompts, session defaults, weather impact analysis, and UI display. Each profile includes TEK guides, substrate recipes, contamination risks, photo references, and regional notes.

**Key constraints**:
- All temperatures in Fahrenheit
- GrowPhase enum: agar, liquid_culture, grain_colonization, substrate_colonization, browning, cold_storage, primordia_induction, fruiting, rest, complete
- Phases a profile lacks: primordia_induction ↔ fruiting and rest → fruiting borrow setpoints (`PHASE_PARAM_FALLBACKS`); a profile with neither fruiting nor primordia setpoints refuses those phases (422). Browning (shiitake) has no fallback: only a profile that defines it can enter it, and its `exit_reminder` (the cold-water soak) is offered by the phase reminder, `GET /next-phase` and the phase advance
- A new phase also needs the monorepo's `scripts/port_enums.py` + `port_species.py` rerun and its pi-ui phase maps
- Built-ins are read-only (PUT returns 409 — clone to customize)
- Some species have unique automation needs: lion's mane (temp swings), king trumpet (elevated CO2 for pinning), reishi (CO2 controls morphology), cordyceps (blue 450nm light required)
- Profile changes should be reflected in the operator's CLAUDE.md section 4b (a git-ignored local spec) if they differ from the documented values
