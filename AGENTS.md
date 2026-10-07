# Agents

Rules for changing SporePrint (the public Pi server + ESP32 firmware repo), for coding agents and contributors. User-facing reference (features, module and API tables, MQTT topics, configuration, security, dependencies) is in [README.md](README.md). Hand a sub-agent its `*-agent` brief plus the two sections before it.

## Repo at a glance

- `server/` FastAPI backend · `firmware/` PlatformIO monorepo · `models/` OpenSCAD enclosures · `ui/dist/` compiled dashboard (never hand-edit) · `config/mosquitto/` broker config + ACL · `scripts/` broker users, signing keys, wiring-SVG generators · `docs/` guides and diagrams.
- This repo is the `sporeprint/` submodule of a private parent monorepo, which owns the dashboard source, the generators that mirror this repo's Builder, species and enum data into it (each has a `--check` mode) and the version-bump script, the only thing that moves versions. Never hand-edit the strings it rewrites: the version in `server/app/main.py`, `server/pyproject.toml` and `server/tests/test_api.py`, `firmware/VERSION.txt`, and README's `**Version:**` banner.
- From the original design spec: [docs/feature-status.md](docs/feature-status.md) (what is not built, and where each "§N" that comments cite lives now; check it before assuming a specced feature exists), [docs/species-reference.md](docs/species-reference.md) (species model, phase rules, special setpoints), [docs/automation-rules.md](docs/automation-rules.md) (rule model, engine gates, built-in rules).

## Commands and rules for every change

| Check | Command |
|---|---|
| Server lint + tests | `cd server && uv sync --python 3.12 --extra dev && uv run ruff check app/ && uv run pytest` (3.12 = the image; uv may otherwise pick a newer Python) |
| Firmware host tests | `cd firmware && pio test -e native` |
| Firmware images | `cd firmware && pio run -e node_esp32 -e node_esp32s3 -e node_esp32s3_n32r16v -e cam -e cam_esp32s3 -e cam_xiao_esp32s3 -e cam_waveshare_s3` |
| Wiring SVGs | `python3 scripts/wiring_svg/build.py` (`--check`); label fit `python3 scripts/wiring_svg/fit_check.py docs/*.svg` |
| Dashboard's built-in Builder data | `cd server && uv run python ../scripts/sync_ui_builder_data.py --check` |
| Compose | `docker compose config --quiet` |

- **No CI runs on push or PR** (`firmware-ci.yml` is manual, `firmware-release.yml` runs on `firmware-v*` tags): these commands are the gate. `tests/test_lint.py` keeps `ruff check app/` green.
- Parallel PlatformIO runs in one checkout share `.pio` and clobber each other: give each its own `PLATFORMIO_WORKSPACE_DIR`. Never run a bare `uv sync` (it syncs exactly: it drops the dev extra and may pick a newer Python); use the command above.
- **Docs are tested.** `server/tests/test_docs_consistency.py` pins README, this file, `docs/**`, the firmware docs, `models/README.md` and the SVGs to the code, BOM and firmware. Fix the doc or the code; never loosen a check. A new profile, table, server package or route changes counts stated in README, `docs/data-flow.md`, `docs/dual-repo-architecture.md` and `docs/architecture-overview.svg`.
- **Changelog:** append to the one `## [Unreleased]` list in `CHANGELOG.md` (server, deploy, enclosures) or `firmware/CHANGELOG.md` (images).
- **Wire contract is additive only:** new payload keys are optional. REST responses, the relay events in `server/app/cloud/` and cloud command frames are additive-only too: the cloud's integrations proxy, the relay and older dashboard bundles call them. `signing_vectors.json` and `ota_manifest_vectors.json` in `firmware/test/fixtures/` stay byte-identical to `server/tests/fixtures/`. Prefer a new telemetry key to a new topic; a new node topic needs a `pattern write sporeprint/%u/<topic>` line in `config/mosquitto/acl.conf`, a branch in `server/app/mqtt.py` and a line in the Builder's `_HARDWARE_CONTRACT` (`builder/service.py`, checked by `tests/test_cross_cluster_builder.py`).
- **GPIO change**, same change: wiring SVGs (edit `scripts/wiring_svg/gen_t*.py` / `parts.py` / `svglib.py`, run `build.py`; `tests/test_wiring_svgs_generated.py` rejects hand edits), the BOM (`server/app/builder/hardware_guides.py`), `docs/hardware-build-guide.md`, the reserved GPIOs in `_HARDWARE_CONTRACT`, the dashboard's built-in Builder data.
- **BOM change**, same change: README tier table, `docs/hardware-build-guide.md` (§0 prices + second-chamber row, §7 cabling), wiring SVGs, the dashboard's built-in Builder data. A price change also moves the monorepo's pi-ui `shopping-page.test.tsx` pins (×1/×4/×12).
- **Builder data goes stale** on any change to the BOM, a `models/` header, a wiring SVG or a PlatformIO env: rebuild `ui/dist` (README → Development) or run `scripts/sync_ui_builder_data.py`, which rewrites only that data. `tests/test_ui_builder_sync.py` enforces it.
- `docs/wiring-overall-system.svg` and `docs/architecture-overview.svg` are hand-maintained (`build.py` generates only the tier SVGs); `fit_check.py` still checks their labels.
- Never remove a driver for hardware any BOM ever recommended ([firmware/docs/drivers.md](firmware/docs/drivers.md)).
- Public docs never name active species; screenshots and examples use gourmet species only.

## firmware-agent

**When**: changing anything under `firmware/`.

**Context**: Two images: the unified node (personality climate / relay / lighting chosen in the setup portal; I²C sensors autodetected at boot) and the camera. Arduino-ESP32 core 3.3.12 on ESP-IDF 5.5.5: pioarduino `55.03.312-1`, pinned in `platformio.ini` `[esp32_base]` (no `[env]` base). `lib/sp_core` (protocol + policy, no Arduino headers) and `lib/sp_drivers` (drivers over an injected HAL) are host-tested; `lib/sp_device` is the Arduino / ESP-IDF layer; `lib/sp_testing` the mock HAL; `boards/` the pin maps (S3 differs from WROOM-32). Envs, OTA, coredumps: [firmware/README.md](firmware/README.md). Signing, TLS, failure containment: [docs/firmware-security.md](docs/firmware-security.md). Wire contract (channels, scenes, sensors, reserved GPIOs, topics, `cmd/*` payloads): `_HARDWARE_CONTRACT` in `server/app/builder/service.py`; change it with the firmware (`tests/test_cross_cluster_builder.py` checks pins and topics).

**Key constraints**:
- Non-blocking: `yield()`, not `delay()`, in loops; `delay()` only for hardware timing.
- C++20 (native env `-std=gnu++20`). PubSubClient 2.8, ArduinoJson 7.4.3, pinned exactly.
- PWM: 25 kHz, 10-bit LEDC on every channel, bound by pin with `ledcAttachChannel(pin, 25000, 10, i)`; relay commands carry `pwm` 0-255 on the wire, lighting `level` 0-1023.
- Telemetry `ts` is epoch seconds once NTP-synced, uptime before (the Pi treats `ts < 1e9` as unsynced). The offline buffer is a 16 KB RAM FIFO, lost on reboot; its frames replay with `"replay": true`. Config lives in NVS.
- `scripts/image_guard.py` fails a build on partition-table drift, < 64 KiB free in the OTA slot, linked ESP-Matter, or the Arduino LEDC allocator in a camera image.
- Core-3 pitfalls already handled, keep them: task WDT reconfigured, never re-initialised (`sp_device/task_wdt.h`); DNS capped at 15 s (`sp_device/bounded_dns.h`); connects bounded by `setConnectionTimeout()`; default node id from `esp_read_mac()`.
- Network OTA (`sp_device/ota_service.cpp`, port 3232) keeps core 2.x's MD5 espota handshake (`sp_core/espota.h`): Pis before 2026-10 speak only that, and core 3.x's stock `ArduinoOTA` only PBKDF2. The Pi's push (`server/app/hardware/ota_push.py`) answers both by nonce length.
- Signed OTA (`sp_core/ota_manifest.h`, `ota_gate.h`): an image built with `SPOREPRINT_OTA_PUBKEY_B64` takes `cmd/ota_manifest {manifest_b64, sig_b64}` and then flashes only that image. The key is a build input (`scripts/fw_version.py`), never set over NVS or MQTT.
- `lib/sp_core/vendor/monocypher/` is upstream Monocypher 4.0.3, unmodified: never edit or reformat it (its `.gitattributes` keeps the bytes as shipped). An upgrade replaces the files and updates the hash table in its README in the same change (`server/tests/test_firmware_vendor.py`).
- Coredumps are store-then-ack: `coredump/chunk` carries `coredump_id` (SHA-256 of the dump); the flash copy is erased only on `cmd/coredump_ack` with that id (`sp_core/coredump_drain.h`).
- Channel safety: all channels off first thing at boot and before an OTA flash; `"state":"off"` always wins; empty payloads are rejected; max-on backstops (30 min, `aux` 60 s, lighting none). After 10 min without MQTT, safe mode switches every channel off; when MQTT returns they stay off, reported as `safety_cutoff`, until the Pi commands them again.

## backend-agent

**When**: changing `server/app/`.

**Context**: Python 3.11+ (image: 3.12), FastAPI, aiosqlite, aiomqtt, python-socketio, Pydantic v2 + pydantic-settings, the Anthropic SDK. Single operator: no user model, login, JWT or RBAC, and no API versioning. The only auth is the optional shared bearer ([docs/auth.md](docs/auth.md)).

**Key constraints**:
- Imports at module top, `anthropic` included. A function-level import only breaks an import cycle, and says so (the uncommented ones already in the tree predate the rule; don't copy them).
- Routers are thin (parsing, 404s, response shaping); logic and SQL live in services. No ORM. (`automation/router.py`'s rule CRUD and one `hardware/router.py` query still run SQL; don't copy them.)
- Package layout: `router.py` → `service.py` → `models.py`. automation/, builder/, chambers/, contamination/, cultures/, experiments/, planner/, sessions/, species/ have all three; labels/ is router-only; notifications/ and retention/ are service-only; integrations/ is a registry of per-vendor drivers.
- DB: `async with get_db() as db:`, one context and one `commit()` per logical operation. `_apply_connection_pragmas` sets `foreign_keys=ON` and `busy_timeout=5000`. Schema: `db.py` `SCHEMA` (WAL, incremental auto-vacuum); migrations via `_add_column_if_missing`.
- Settings: `SPOREPRINT_` prefix; forward every new `Settings` field in `docker-compose.yml` (`tests/test_docker.py`). Deps are locked in `server/uv.lock` (the image installs exactly those): run `uv lock` after editing `pyproject.toml`.
- Background loops (MQTT, weather polling, retention, cloud connector, weather-model retrain, nightly weather aggregation, node-liveness sweeper, phase reminders, integrations health sweeper) start in `main.py` lifespan and are cancelled on shutdown.
- Shared helpers, never a second copy:

  | Need | Helper |
  |---|---|
  | Rule DB I/O | `deserialize_rule_row()` / `serialize_rule_data()` (`automation/service.py`) |
  | OFF payloads | `drop_duty_from_off()` / `is_off_command()` (`automation/service.py`) |
  | `vision_frames` rows | `_deserialize_frame()` (`vision/service.py`) |
  | Claude calls | `anthropic.AsyncAnthropic` (never `Anthropic`), model `settings.claude_model` (never a literal), `claude_response_text()` + `parse_claude_json()` (never raises) from `vision/service.py` |
  | Telemetry buckets | `_RESOLUTION_BUCKETS` (`telemetry/service.py`); history falls through to rollups past 7 days |
  | Active session | `get_active_session()`; per node `get_active_session_for_node()` / `get_active_session_for_chambers()` (`sessions/service.py`) |
  | Phase validation | `phase_error()`, `InvalidPhaseError`, `PHASE_PARAM_FALLBACKS` (`sessions/service.py`) |
  | Weather provider | subclass `WeatherProvider` (`weather/providers.py`: `fetch_current()`, `fetch_forecast()`), register in `get_provider()` |
- Import cycles: `automation/engine.py` imports `sessions.service` at module top, and `sessions.service` imports a dozen app modules at its top (the NOTE there), so nothing `sessions.service` imports, directly or indirectly, may import `sessions.service` or the engine at module level. `automation/engine.py` imports `app.integrations._actions`, so integrations and smart_plugs must not import the engine.
- A published non-automation OFF calls `automation.engine.note_actuator_off()`; sessions reaches it through `sessions.service.add_actuator_off_listener()` and must not import the engine.
- Rule firing: INSERT `automation_firings` `status='pending'` → `mqtt_publish` (returns bool) → UPDATE `status='sent'|'failed'`. Never write `sent` first.
- Changing a shipped built-in rule (`automation/templates.py`): first record its exact old form in `LEGACY_BUILTIN_RULES` or a `PRE_*_BUILTIN_RULES` table folded into `SUPERSEDED_BUILTIN_RULES`, or every existing Pi keeps the old rule; update the built-in table in [docs/automation-rules.md](docs/automation-rules.md#changing-a-built-in-rule) (tested) in the same change.
- Manual overrides: the `manual_overrides` table is the truth. `await ensure_overrides_loaded()` before reading the cache; write with async `set_override()` / `clear_override()`.
- Telemetry timestamps: `ts < 1e9` is firmware uptime — stamp arrival time. Replayed (`"replay": true`) frames and out-of-order frames (older than the node's newest live `ts`, by at most 120 s) are stored at their own time but never evaluated by rules or pushed live. A frame more than 120 s behind the node's newest `ts` is a clock step-back: it re-baselines the node and stays live. The Pi's own clock never decides liveness (`mqtt.py` `_classify_frame`).
- `session_events` is append-only. Retention rollups use `INSERT ... ON CONFLICT DO UPDATE` with count-weighted merging, never `INSERT OR IGNORE` + `DELETE`.
- `hardware_nodes` writes live in `hardware/service.py`, with two exceptions: `mqtt.py`'s ingest (status and heartbeat upserts, health `channels`, the telemetry `last_seen` touch, the reserved-id purge: the hot path, which is the "V20 exception" `hardware/service.py` cites) and `main.py`'s liveness sweeper.
- Broker: anonymous clients are refused, so every `aiomqtt.Client(...)` gets `settings.mqtt_username` / `mqtt_password`. Logins and ACL scoping: README → Security and [config/mosquitto/README.md](config/mosquitto/README.md).
- Shelly Gen2+ plugs (`plug_type` `shelly_gen2`) need MQTT prefix `shellies/<role>`: the ACL grants the server only `shellies/+/rpc`, so `automation/smart_plugs.py` refuses any other prefix.
- Send node commands only through `mqtt.mqtt_publish`: it signs every `cmd/*` frame with `SPOREPRINT_MQTT_HMAC_KEY` and, with no key, refuses to send when `SPOREPRINT_MQTT_REQUIRE_SIGNING` enforces signing ([docs/firmware-security.md](docs/firmware-security.md)).
- Bearer gate: `app/auth.py` `ApiKeyMiddleware` guards every `/api/*` route and the Socket.IO `connect` once `SPOREPRINT_API_KEY` is set; with no key the server boots only if `SPOREPRINT_ALLOW_UNAUTHENTICATED=true`. Public paths: [docs/auth.md](docs/auth.md). No new route bypasses the gate without explicit justification.
- Coredumps: `hardware/coredumps.py` `ingest_chunk` stores the dump durably (temp file, fsync, rename) before `mqtt.py` publishes `cmd/coredump_ack`.
- OTA manifests: the Pi self-update (`cloud/ota_manifest.py`) verifies against the locally pinned key only, never a key carried by the command; node pushes reuse the format (`hardware/node_manifest.py`).
- The cloud connector (`cloud/`) stays a no-op unless configured (README → Cloud Connector).
- CORS stays the LAN-only `_LAN_ORIGIN_REGEX` in `main.py`: never `allow_origins=["*"]` (any site the operator visits could drive the hardware), never `sporeprint.ai` (cloud traffic arrives over the relay).
- Health: `psutil`, with `sensors_temperatures()` in try/except (macOS). Reliability counters (`uptime_ts_clamps`, `mqtt_supervisor_restarts`) appear under `reliability` in `GET /api/health/detail/system`.
- BOM lines (`builder/hardware_guides.py`): cabling and consumables are real lines (categories `wiring` / `hardware`). `shared=True` marks per-installation lines (Pi side, bench breadboard) the chamber count does not multiply. What chambers use up (kits, spools, zip ties, heat-shrink, grommets) is a per-chamber pack line: `quantity` per chamber, `pack_size`, `shared_units` (the Pi case's share of the pack, from the `models/README.md` shopping list) and `unit` (feet, grams, or one piece of a mixed kit).

## frontend-agent

**When**: working on the dashboard. Its source and rules live in the monorepo (`frontend/packages/pi-ui`, its `pi-ui-agent` guide). This repo ships only `ui/dist` (never hand-edit; rebuild per README → Development), served by the `ui` nginx container (`ui/nginx.conf` proxies `/api` and `/socket.io`), and `scripts/sync_ui_builder_data.py`, which refreshes the bundle's built-in Builder data. The Builder page reads `/api/builder/*` live and falls back to that built-in copy.

## test-agent

**When**: writing or running tests.

**Context**:
- Backend: pytest + pytest-asyncio (`asyncio_mode = "auto"`) in `server/tests/`. Each test gets a temp-file SQLite (not `:memory:`: `get_db()` opens new connections) via conftest's `settings.database_path` patch. Foreign keys are live: insert the parent row first.
- The `client` fixture runs the full lifespan with the long-running loops (MQTT, weather, retention, cloud, retrain, weather aggregation, node-liveness sweeper) stubbed; autouse fixtures reset the engine's module state.
- `mock_mqtt` returns the publish list with a `.mock` attribute; `mock_mqtt.mock.return_value = False` simulates a broker that is down.
- Guard suites: `test_docs_consistency.py`, `test_lint.py` (`ruff check app/`), `test_firmware_vendor.py` (vendored Monocypher hashes, LF endings, licence), `test_ui_builder_sync.py`, `test_wiring_svgs_generated.py`, `test_svg_text_fit.py` (skips without Chrome), `test_models_router.py` (skips without OpenSCAD; set `SPOREPRINT_OPENSCAD`), `test_docker.py` (compose ↔ `Settings`).
- Firmware: Unity suites in `firmware/test/` ([README](firmware/test/README.md)), `pio test -e native`.

## species-agent

**When**: adding or changing species profiles.

**Context**: `server/app/species/profiles.py` drives the rules, vision prompts, session defaults, weather impact, wizard and dashboard. Model, phase rules and the special species: [docs/species-reference.md](docs/species-reference.md).

**Key constraints**:
- All temperatures in Fahrenheit.
- GrowPhase enum: agar, liquid_culture, grain_colonization, substrate_colonization, browning, cold_storage, primordia_induction, fruiting, rest, complete
- Built-ins are read-only (PUT returns 409): clone under a new id.
- Put quirks in profile data the generic rules read (`co2_min_ppm`, `light_spectrum`, `exit_reminder`, `fae_mode`), not in a new species-named rule ([docs/automation-rules.md](docs/automation-rules.md)).
- `tests/test_species_spec_setpoints.py` pins key setpoints; `docs/species-reference.md` tables the special species; a new profile changes the counts README and the species reference state. After any profile change, rerun the monorepo's `scripts/port_species.py` and check it with `--check` yourself (nothing runs it automatically); a new phase also needs `port_enums.py` and the pi-ui phase maps.
- Active species' setpoint tables stay out of the public docs.
