# Changelog

All notable changes to the public SporePrint Pi-side repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.5] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.4] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.3] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.2] - 2026-05-01

Lockstep version bump only — no Pi-side, server, UI, or firmware changes. v4.0.2 fixes a cloud-web middleware short-circuit that was 5xx-ing Railway's healthcheck on the v4.0.1 deploy.

## [4.0.1] - 2026-05-01

Lockstep version bump only — no Pi-side code, server, UI, or firmware changes in this release. All v4.0.1 deltas are in the parent cloud monorepo (cloud-web landing page, Dockerfile + start.sh runtime aliasing, middleware allow-list expansion, GHA deploy-job disable, jsdom lockfile sync, placeholder cleanup). The submodule pointer moves with the parent so `release-guard.sh`'s lockstep invariant stays green.

## [4.0.0] - 2026-04-30

Major version bump in lockstep with the cloud parent repo's v4 migration (Vite SPA at `/app/*` → Next.js 15 App Router at `/`). Pi-side scope this release: OTA progress event fan-out (archaeology #7), Ed25519 OTA signing helpers, Pi UI v4 dist bundle, and a `/simplify` pass on the cloud connector + settings router. No GPIO / I2C / PWM pin changes; firmware-specific notes live in `firmware/CHANGELOG.md#400`.

### Added

- **OTA progress events (v4 archaeology #7).** `server/app/cloud/ota.py` now emits per-step progress via a new `_emit_step()` helper that calls `forward_event("ota_step", payload)` on the cloud relay. Cloud parent persists each step into the new `ota_progress_events` Supabase table so the mobile app + cloud-web shell can render a real progress bar instead of polling for terminal success/failure. `_promote_and_restart` was split into `_promote` and `_restart_unit` so each phase emits its own event.
- **OTA signing helpers in `scripts/`** — `generate-ota-keypair.py` (Ed25519 keypair generator) and `sign-ota-bundle.py` (signs an OTA tarball with the operator's private key). The cloud parent verifies the signature before promotion via `PUT /settings/ota-pubkey`. Operator workflow documented in `docs/firmware-security.md`.
- **Pi UI v4.0.0 dist bundle** in `ui/dist/`, compiled from the parent monorepo's `frontend/packages/pi-ui/`. Pi-served LAN UI now matches the cloud-web design system (warm substrate palette, JetBrains Mono numerics, shared SporePrintMark canvas).

### Changed

- **`server/app/cloud/ota.py` simplified** — removed the unused `_promote_and_restart` back-compat wrapper after callers were updated to the split `_promote` + `_restart_unit` pair. Stripped narrational comment overhead (-136 LOC).
- **`server/app/settings_router.py` simplified** — removed five redundant `try/except Exception → 500` patterns that just leaked exception text instead of letting FastAPI's default error handler do the right thing (-26 LOC).
- **`server/app/cloud/service.py`** — `forward_event()` extended to accept the new `ota_step` channel alongside the existing telemetry/alert channels.
- **Lockstep v4.0.0 version bump** with the cloud parent. No Pi-protocol break; v3.4.x Pis interoperate with a v4 cloud and vice-versa for telemetry, command signing, pairing, and HMAC. Web-app surface URL change (`/app/` → `/`) is parent-only.

### Fixed

- (none — `/simplify` cleanup + additive OTA-step plumbing only.)

## [3.4.10] - 2026-04-24

Lockstep version bump — no Pi or firmware changes. Cloud-side parent repo introduced a `KVCache` protocol for ephemeral in-pod state so a future Redis migration is drop-in. Firmware build unchanged.

## [3.4.9] - 2026-04-24

Fresh archaeology sweep of v3.4.8 (`analysis/02-security.md` in the parent repo). All Critical, High, Medium, Low + operator-feedback items closed in one pass. Firmware grew real defense-in-depth at the MQTT layer; the cloud relay gained tier/ownership re-checks + rate limiting + `cmd_id` correlation; the Pi server got structured logs + split MQTT ACL + synced dependency pins. Firmware-specific narrative in `firmware/CHANGELOG.md#349`.

### Added

- **HMAC verification of inbound MQTT commands on every ESP32 node** (`sporeprint_common/frame_verify.{h,cpp}`). Closes Sentinel **C-1** — the cloud-signed chain now extends past the broker to firmware. Shared canonical-JSON serialization is byte-identical to the Python `signing.py`. Uses mbedtls (part of ESP-IDF — no new dep).
- **NTP sync at WiFi connect** so the 30-second replay window on firmware command frames is meaningful (`wifi_manager.cpp`).
- **`scripts/provision-node.sh`** — generates an HMAC key, writes to `server/.env`, prints the `pio run` commands to bake the key into each node's NVS via `-DSPOREPRINT_PROVISION_HMAC`.
- **`esp_task_wdt` on climate / lighting / cam nodes** (M-6). Parity with relay_node; timeouts tuned per node (30 / 10 / 60 s).
- **`esp_reset_reason()` + wifi/mqtt reconnect counters** in every heartbeat (`heartbeat.cpp`).
- **OTA lifecycle MQTT events** on `sporeprint/<id>/ota` (start / success / error).
- **Minimum 12-char OTA password** (L-6).
- **Split Mosquitto users**: `sp-cmd` / `sp-telemetry` / `sp-3p`. Replaces the single `server readwrite #` account. `scripts/rotate-mqtt-creds.sh` rotates them.
- **`docs/firmware-security.md`** — operator guide for secure boot v2 + flash encryption + signed OTA.
- **Firmware `VERSION.txt`** + `SPOREPRINT_FW_VERSION` build flag — no more hardcoded `"0.1.0"`. `scripts/bump.sh` keeps it in lockstep.
- **`firmware/CHANGELOG.md`** — firmware changes now have their own narrative.
- **`.github/workflows/firmware-ci.yml`** — `pio run` on all four envs for every PR touching `firmware/**` (Risk 15).
- **Unity test-harness scaffold** at `firmware/test/` (Prescription 6.3.14 — opens the path).
- **`/api/vision/frame` whitelisted** in the Pi ApiKeyMiddleware (L-9).
- **Structured JSON logs on the Pi** with contextvar-based `request_id` threading (`logging_config.py` + `_request_id_mw.py`). Debt 5.
- **`_task_registry` wired** — every long-running supervisor registers + transitions status. Previously declared but never called (Debt 4).
- **`DesktopShell` component** (`app/src/components/web/DesktopShell.tsx`) — shared shell for the 18 desktop pages. Migration tracker in `app/src/pages/web/README.md`.

### Changed

- **Relay command handler refuses bare `{}` payloads** (M-5). Previously defaulted `state=on, pwm=255`.
- **Case-insensitive `state` parse** in relay_node.
- **`millis()` wrap-safe `offAt` compare** (L-1).
- **Cam `server_url` allow-list** (H-1). Allowed: paired Pi LAN, `sporeprint.local`, `sporeprint.ai`, RFC1918.
- **Climate alerts emit separately** (Debt 6) — simultaneous conditions no longer collapse.
- **MQTT inbound buffer 512 → 1024 bytes** (L-2). Oversize frames now explicitly dropped with a Serial log.
- **`OfflineBuffer::BUFFER_FILE` constant removed** (Debt 10).
- **`safety_cutoffs` + `captureFail` + `captureSuccess` + `avgLatencyMs` counters now increment** (Debt 3).
- **Pi `pyproject.toml` gains upper-bound caps** on every dep to match cloud policy (L-3).

### Fixed

- **`mqtt_publish()` signs every cmd/\* frame** with `settings.mqtt_hmac_key` before publishing. Paired with firmware verify, the Pi↔ESP32 hop is now HMAC-authenticated end-to-end.

## [3.4.8] - 2026-04-23

Firmware CI hygiene — all four node builds now compile clean against a pinned `platformio/espressif32@6.13.0` platform. Pre-existing build breaks from mixed Arduino-ESP32 API usage fixed without changing any GPIO / I2C / PWM pin assignment. No protocol or runtime behavior change.

### Changed

- **`firmware/platformio.ini`:** pinned `platform = espressif32@6.13.0` (official, Arduino-ESP32 core 2.x). Previously unpinned — fresh `pio install` pulled whatever latest happened to be, and the code's mix of core-2.x and core-3.x APIs compiled against neither.
- **`firmware/src/relay_node/main.cpp`:** replaced core-3.x `ledcAttach(pin, freq, resolution)` with the core-2.x `ledcSetup(channel, freq, resolution)` + `ledcAttachPin(pin, channel)` idiom. GPIO assignments (`CHANNEL_PINS[] = {25, 26, 27, 14}`) unchanged.
- **`firmware/src/lighting_node/main.cpp`:** same PWM API swap. GPIO assignments unchanged.
- **`firmware/src/climate_node/main.cpp`:** ClosedCube SHT31D 1.5 `readSerialNumber()` returns `uint32_t` directly, not an `SHT31D` struct. Reworked the sensor-present probe to check the serial number is non-zero instead of inspecting a `.error` field that doesn't exist on the 1.5 API. I2C address (`0x44`) unchanged.

### Fixed

- All four PlatformIO envs (`relay_node`, `climate_node`, `lighting_node`, `cam_node`) build cleanly from a fresh `pio install`. Post-install dev setup also needs `python3 -m pip install intelhex` for esptool's bootloader-assembly step on macOS with Homebrew Python 3.14.

## [3.4.7] - 2026-04-23

Independent code-archaeology sweep. 12 fixes across firmware safety, server concurrency, UI error visibility, and ops hardening. No breaking protocol changes; mobile + cloud clients unchanged.

### Added

- **Toast notification system** — `ui/src/stores/toastStore.ts` + `ui/src/components/ui/Toaster.tsx`. Replaces 26 silent `.catch(() => {})` / `catch { /* ignore */ }` swallows across 13 pages/components. Fetch failures now log with context to the console and surface a dismissable toast in the UI. `reportFetchError(context, err, userMessage)` is the single entry point.
- **`allow_unauthenticated` config flag (`server/app/config.py`)** — explicit opt-in for running the Pi without `SPOREPRINT_API_KEY`. Default is `False`; the server refuses to boot when both the key is empty and the flag is false. When opted in, a loud startup WARNING replaces the silent LAN-trust behavior. `docker-compose.yml` defaults the env var to `false` — fresh stacks must set it to `true` explicitly or provide an api_key.
- **`_SESSION_UPDATE_COLUMNS` whitelist (`server/app/sessions/service.py`)** — defense-in-depth for the (already Pydantic-typed) update column set.
- **Docker healthchecks** — `server` (urllib → `/health`), `mqtt` (`mosquitto_sub` on `$SYS/broker/version`), `ntfy` (`wget /v1/health`). `depends_on` upgraded to the long form with `condition: service_healthy` so `server` waits for the broker to actually accept subscriptions and `ui` waits for the API to respond.
- **AbortController for Vision analyze** — `ui/src/pages/Vision.tsx` now cancels in-flight `POST /vision/frames/{id}/analyze` when the user clicks a different frame. `api.post`/`get`/etc. accept an optional `{ signal }` option. Prevents stale responses clobbering the newer frame's state.

### Changed

- **`sessions.update_session` collapsed from N-per-column UPDATEs to a single `UPDATE ... COALESCE(?, col) ...`** statement. Partial failure mid-loop can no longer half-write a row; also 1 DB round-trip instead of up to 12.
- **`automation.engine` — `_state_lock: asyncio.Lock`** guards read-modify-write spans on `_overrides`, `_rule_cache`, `_last_fired`. `_load_overrides_from_db` fetches into a fresh dict and atomically swaps under the lock so concurrent evaluators never observe a cleared cache. `get_overrides` expiry sweep is lock-protected.
- **`cloud.service` — `_replay_lock: asyncio.Lock`** guards `_seen_command_ids` OrderedDict. Check-and-insert is atomic; two concurrent frames carrying the same command id can no longer both pass the dedup test. Socket emit is done outside the lock.

### Fixed

- **Firmware FW-1 (`relay_node/main.cpp`):** MQTT `duration_sec` is now clamped to `[1, 3600]` seconds before computing the off-at deadline. Previously, a huge or negative payload could wrap the `millis()` arithmetic and latch a relay ON indefinitely — the worst failure mode for a heater/humidifier.
- **Firmware FW-2 (`relay_node/main.cpp`):** ESP32 task watchdog armed at 10 s. `loop()` resets on each iteration; any deadlock in MQTT/OTA/WiFi now triggers a reboot. Safe state on reset is all-channels-OFF (setup() enforces).
- **Firmware FW-3 (`wifi_manager.cpp`):** Captive portal now has a 10-minute timeout. An abandoned provisioning session reboots the node rather than leaving it stranded in AP mode forever.
- **Firmware FW-4 (`climate_node/main.cpp`):** `read_interval_ms` and `publish_interval_ms` MQTT payloads are clamped to sensible ranges (1s–10min read, 5s–1h publish) with Serial warn on out-of-range. A `read_interval_ms=0` payload previously would busy-loop `readSensors()` and starve the MQTT/OTA tasks.
- **README:** removed broken `ui/public/mushroom-logo.svg` `<img>` reference. Renamed two `CLAUDE.md` references to `AGENTS.md` (the file that actually exists in this repo).
- **Tests:** `server/tests/conftest.py` sets `SPOREPRINT_ALLOW_UNAUTHENTICATED=true` at import so the test process can boot under the new secure-by-default behavior.

## [3.4.6] - 2026-04-23

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.6 release-tooling fix — the parent repo added `scripts/sync-after-merge.sh` and a bump preflight to prevent submodule-pointer drift after rebase/squash merges on GitHub. See the parent repo's `CHANGELOG.md` for the full context.

## [3.4.5] - 2026-04-22

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.5 `/simplify` pass over the v3.3.10 → v3.4.4 window (batched `metric_active_alerts` reads on every telemetry ingest, parallelized daily-summary fan-out, bounded caches, routed `alerts/escalation.py` through its persistence layer, extracted RevenueCat REST helper, narrative-ID comment sweep). See the parent repo's `CHANGELOG.md` for the full list.

## [3.4.4] - 2026-04-22

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.4 `/simplify` cleanup pass (code-reuse consolidation, event-loop offloading for DNS, parallelized tier reconcile, dead-import/dead-comment sweep). See the parent repo's `CHANGELOG.md` for the full list.

## [3.4.3] - 2026-04-22

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.3 (`@xmldom/xmldom` CVE override in the mobile app's dependency tree).

## [3.4.2] - 2026-04-22

No Pi protocol changes. Version bumped in lockstep with the cloud-side v3.4.2 release (catch-up bump covering the gap-close + no-deferrals work that landed between v3.4.1 and this version).

### Changed

- **L-4 `_configure_token` multi-slot dict.** Pre-v3.4.2 carried a single `dict | None` global — a second parallel `/pair` would overwrite the first's token and invalidate it before the first client could `/configure`. Now keyed by token in `_configure_tokens` with TTL sweeps and a 32-entry hard cap. Parallel `/pair` sessions coexist; pair-spam attackers can't blow memory.

## [3.4.1] - 2026-04-21

No Pi-side functional changes. Version bumped in lockstep with the cloud repo's fifth-archaeology close-out — see the cloud CHANGELOG for v3.4.1 for the commercial-side fixes (SSRF guard on `/devices/pair`, tier-cache invalidation on downgrade, `_device_sids` race fix, Pi-emit event pass-through handlers, CSP tightening, AI quota race lock, and 20 new regression tests).

All Pi protocols (HMAC signing, pair-verify, MQTT auth, bearer API-key gate) remain byte-compatible with v3.3.3+ / v3.4.x clouds.

## [3.4.0] - 2026-04-21

No Pi-side functional changes. Version bump to stay in lockstep with the commercial cloud release (tier-model clarification on the cloud side — see the cloud repo's CHANGELOG for details).

### Changed

- `scripts/bump.sh` now matches the cloud-side bump script: auto-inserts a CHANGELOG skeleton for the new version, updates the README's `**Version:**` banner if present, and prints a doc-drift warning for any lingering `v${CURRENT}` references in README / docs.

### Documentation

- README banner rewritten to explain the new commercial/OSS split: the Pi repo stays AGPL-3.0 free software; cloud-relay/mobile/web-app are paid. Pi-standalone users are unaffected.
- Added historical release callouts for v3.3.3 / v3.3.4 that were previously only in the cloud repo's CHANGELOG.

## [3.3.4] - 2026-04-20

Cloud-side fourth-archaeology close-out — the Pi changes in this release are support endpoints for the cloud's updated pairing + command-signing flows.

### Added

- **`GET /api/cloud/pair-verify?configure_token=<tok>`** (`server/app/cloud/router.py`). Closes S-M-11: the cloud now calls this endpoint from its own network during `POST /devices/pair` to confirm the configure_token really was issued by this Pi. Prevents a hostile LAN host from tricking the mobile app into writing an attacker-chosen device_token into Supabase.
- Signing-frame rejection categories (`server/app/cloud/service.py`). The Pi now tags rejection reasons as `clock_skew`, `signature_mismatch`, or `bad_frame` so the cloud + mobile UI can distinguish a drifting RTC-less Pi from a real signature mismatch (P2-10 / E-2).

### Unchanged

- HMAC signing protocol, nonce-cache shape, bearer-token scheme, MQTT auth, OTA password gate — all stable since v3.3.1.

## [3.3.3] - 2026-04-19

Pi-side hardening for command-signing freshness + replay protection.

### Added

- Persistent replay-nonce cache — survives Pi reboots so a Pi that restarts mid-attack can't accept a previously-seen command id within its 30s HMAC window.
- `scripts/setup-pi.sh` now installs and configures `chrony` so the Pi's clock stays within ±30 s of the cloud. Prior: a Pi whose clock drifted (common after long power outages on an RTC-less unit) would silently reject signed commands as stale.

### Fixed

- Clock-drift rejections now log with enough detail for operators to tell "bad signature" apart from "your clock is wrong."

## [3.3.2] - 2026-04-18

Cloud-parity release following the second-pass archaeology audit. Pi-side hardening in v3.3.0/v3.3.1 was airtight; this release extends the same discipline to the rest of the system and closes the remaining audit items.

### Security

- **Nonce cache is now a real FIFO (P6).** `server/app/cloud/service.py::_seen_command_ids` switched from `set` with arbitrary `pop()` to `OrderedDict` with `popitem(last=False)`. A burst of >1024 distinct ids no longer lets an earlier id be replayed inside the 30s HMAC window.

### Fixed

- **Pi-local alerters forward to cloud push (P2).** `engine._check_safety_thresholds`, `vision.analyze_frame_claude`, and `main._node_liveness_sweeper` now call `forward_event(...)` alongside their local ntfy notification. Premium mobile subscribers actually receive push alerts when thresholds breach or a node goes offline. Prior: local ntfy fired, cloud push never did.
- **Safety watchdog survives Pi restart (P10).** A new `safety_watchdogs` SQLite table records each armed `safety_max_on_seconds` auto-off. On boot, `rehydrate_safety_watchdogs` re-arms watchdogs whose `expires_at` is in the future and publishes OFF immediately for any whose expiry elapsed while the Pi was down. Prior: a reboot with a heater ON left the actuator stuck ON with no watchdog.
- **`push_log.read` vs `is_read` inconsistency resolved (Q10).** The cloud layer standardized on `is_read` (matches CLAUDE.md); migration renames the column if an older deployment had `read`.

### Changed

- **Pi router raw-SQL refactor (P12).** `automation/router.py`, `vision/router.py`, `hardware/router.py` now delegate all DB access to service-layer helpers. New `hardware/service.py`; expanded `automation/service.py` and `vision/service.py`. Router files drop to ~100 LOC each. Closes 3 of the PV1-PV3 layering violations.
- **`manual_overrides` + `safety_watchdogs` share a transaction on override set.** Prior version held two separate connections concurrently and deadlocked under SQLite's single-writer contract; the watchdog cancel + DB delete now happen inline so the override + watchdog records stay coherent.

### Added

- `server/app/automation/service.py` — new CRUD helpers (`list_rules_with_created_at`, `get_rule`, `create_rule`, `update_rule`, `delete_rule`, `toggle_rule`, `list_firings`) extracted from the router.
- `server/app/hardware/service.py` — new module with `list_nodes`, `get_node`, `send_command` + the regex validators.
- `server/app/vision/service.py` — `get_active_session_id`, `insert_frame`, `update_analysis_local`, `update_analysis_claude`, `get_frame_by_id`, `apply_user_label`.
- `safety_watchdogs` SQLite table for persistent watchdog state.
- `server/tests/fixtures/signing_vectors.json` — shared golden-file fixture with the cloud side. Drift trips tests on whichever runtime moved.
- `server/tests/test_signing_golden.py` — asserts the Pi's `_canonical` + `verify_frame` match the fixture byte-for-byte.

### Migration

- **Apply database changes by restarting the server** — `init_db` creates `safety_watchdogs` automatically.
- **No breaking protocol changes** — v3.3.1 and v3.3.2 Pis interoperate with a v3.3.1 cloud; the command contract is unchanged.

## [3.3.1] - 2026-04-17

Incremental security release — closes S3 (cloud command signing) end-to-end.

> ### ⚠️ BREAKING CHANGE — v3.3.1 Pi requires a v3.3.1 cloud relay
>
> **The Pi now refuses unsigned command frames.** Consequences:
>
> - **v3.3.1 Pi ←→ v3.3.0 cloud**: every mobile-app command is rejected with `Signature check failed: missing signature`. Remote control is fully broken until both sides are upgraded.
> - **v3.3.0 Pi ←→ v3.3.1 cloud**: commands still execute (old Pi ignores the new signature field) but nothing is protected — the cryptographic guarantee only holds when both ends verify.
>
> Deploy both sides together. The HMAC key is the already-provisioned `device_token` from pairing — no new operator secret.

### Security

- **Cloud command frames are now HMAC-SHA256 signed (S3 full closure).** Every `command` frame forwarded by the cloud relay carries a `signature` field covering the canonical JSON form of the frame and a `ts` (epoch seconds). `cloud/service.on_command` verifies signature + replay window (`±30s`) BEFORE checking tier, command id, target, or channel. A compromised cloud relay, a third party with socket access, or anyone who has re-authed their device socket cannot forge commands without the Pi's `cloud_token`. Replaces the v3.3.0 defense-in-depth pattern (tier string + id LRU + target allowlist) as primary — those remain as second-line guards.

  New file: `server/app/cloud/signing.py` mirrors the cloud-side signer byte-for-byte.

  Regression coverage: `server/tests/test_cloud_signing.py` — tamper, wrong key, missing/stale/future `ts`, empty key, key-order stability.

### Migration

- **Both sides must be upgraded together.** An old Pi paired to a new cloud will refuse all commands (old Pi doesn't verify; new cloud sends signed frames that old Pi doesn't know about — but the Pi side gate is new, so "old" means pre-v3.3.1). A new Pi paired to an old cloud will refuse all commands (no signature present). There is no opt-out flag — this is the contract.
- **No operator action required beyond pulling both repos.** The shared secret (`device_token` / `cloud_token`) is already in place from pairing; nothing new to provision.

## [3.3.0] - 2026-04-17

Security + stability release closing every critical finding from an external code audit. **Upgrading is strongly recommended for any Pi running unattended.**

### Security

- **MQTT broker is no-anonymous by default.** `config/mosquitto/mosquitto.conf` now sets `allow_anonymous false`, a `password_file`, and a per-role `acl.conf`. `setup.sh` provisions the `server` credential on first run (random 40-char). Firmware nodes read their credentials from NVS via `MqttManager._connect` (`mqtt_user` / `mqtt_pass`). The broker is bound to `127.0.0.1` in `docker-compose.yml`; never expose port 1883 to the internet. Prior to this release, any device on the LAN could publish `sporeprint/relay-01/cmd/heater {state:"on",pwm:255}` directly to the broker and the relay would obey.

- **`/api/cloud/configure` requires a short-lived `configure_token`.** `/pair` now validates the 6-digit code (with an 8-attempt / 10-minute lockout) and issues a `configure_token` in the response. `/configure` rejects any request without a matching token, rejects values containing `\n` / `\r` / `=` (newline-injection defense), resolves the `.env` path from the package root (not process CWD, which `/` under systemd), and writes atomically via `tempfile + os.replace` with `chmod 600`. Prior: unauthenticated LAN POST could rewrite `.env` and plant arbitrary env vars on next restart.

- **Backend bearer-token auth (opt-in).** New `app/auth.py` `ApiKeyMiddleware` gates every `/api/*` route plus the Socket.IO `connect` handshake when `SPOREPRINT_API_KEY` is set. Whitelist: `/api/health`, `/api/cloud/pair`, `/api/cloud/pairing-code`. `setup.sh` generates a key on first run so fresh installs are authed by default. Closes free-Claude-billing exhaustion, API-key exfil-by-substitution on the settings router, and ntfy-topic hijack.

- **Vision upload path traversal closed.** `POST /api/vision/frame` validates `X-Node-Id` against `^[a-zA-Z0-9_-]{1,32}$` and asserts the resolved write path stays inside `vision_storage`. Prior: a header value of `../../etc/passwd_image` would attempt to break out of the storage dir.

- **Hardware command topic lockdown.** `POST /api/hardware/nodes/{id}/command` drops any caller-supplied `topic` field and constructs the topic server-side from the URL path. Channel must match the safe-charset regex.

- **Cloud command channel HMAC-signed (S3 — full closure in v3.3.1).** v3.3.0 hardened this with defense-in-depth (id-replay LRU, target regex, registered-target check). v3.3.1 closes the remaining gap: every command frame forwarded by the cloud relay is now HMAC-SHA256 signed over a canonical JSON form of the payload using the Pi's `cloud_token` as the key. `cloud/service.on_command` verifies the signature and a `ts` timestamp (30-second replay window) BEFORE any other check — a compromised relay or a third party with socket access cannot forge commands without the shared secret. The signing helper (`server/app/cloud/signing.py`) mirrors the cloud-side implementation byte-for-byte.

- **OTA password enforcement.** `OTAManager::begin` refuses to call `ArduinoOTA.begin()` when `ota_pass` is unset or equals the legacy default `"sporeprint"`. Nodes log a warning until the operator sets a strong password via the captive portal.

- **python-multipart bumped to `>=0.0.18`** to close CVE-2024-24762 (permitted by the previous `>=0.0.6` floor).

### Fixed

- **`safety_max_on_seconds` is now actually enforced (R15 / P14).** Previously the field existed on `AutomationRule` and was used by built-in templates, but nothing in the codebase ever turned an actuator off based on it. Now `_fire_rule` schedules a cancellable `asyncio.Task` (`_safety_auto_off`) whenever it successfully publishes `state='on'` with a non-zero `safety_max_on_seconds`. The task publishes `state='off'` after the declared delay and writes an `automation_firings` row with `rule_name='safety_max_on_seconds:<original>'` so the timeout is visible in the audit log. Pending watchdogs are cancelled when a subsequent rule publishes `state='off'` for the same `target:channel`, or when an operator sets a manual override (operator owns timing while the override is in place). New regression suite `test_safety_max_on.py` covers all four behaviours. Fire-risk closure.

- **Dead `server/app/websocket/` package removed (P11 / V19 / D1).** `register_events` and `broadcast_telemetry` had no callers — Socket.IO handlers and emits are centralised in `main.py` and the various service modules. The module was a trap for new contributors looking for "where do sockets get wired up." Gone.

- **Firmware uptime timestamps no longer corrupt history (DATA-1).** `mqtt._handle_message` treats any `ts < 2020-01-01` as firmware uptime-seconds (the `millis()/1000` written by the offline-buffer drain) and replaces it with the server's receive time. A counter (`uptime_ts_clamps`) surfaces on `/api/health/detail/system` so operators can see when it triggers. Prior: every WiFi reconnect on any node inserted 1970-epoch rows into `telemetry_readings`.

- **Automation audit log no longer lies during MQTT outages (SAFETY-2).** `_fire_rule` now inserts `automation_firings` with `status='pending'`, attempts `mqtt_publish` (which returns a bool), and only then updates the row to `status='sent'` (publish succeeded) or `status='failed'` with the error captured. Prior ordering was publish-first, log-second: during the 5-second MQTT reconnect window, the publish silently dropped but the audit row still recorded a successful fire.

- **Manual overrides survive reboots (SAFETY-1).** `manual_overrides` DB table is now the source of truth for `engine._overrides`. `set_override` / `clear_override` / `get_overrides` read-through and write-through; `ensure_overrides_loaded` hydrates the in-memory cache on first use and prunes expired rows. Prior: operator safety locks were RAM-only and silently evaporated on every Pi reboot.

- **MQTT consumer no longer dies silently (RELIABILITY-1).** `_handle_message` is wrapped in `try/except Exception` with `log.exception`. `start_mqtt` body is wrapped in a `while True` supervisor with a 5-second backoff and a restart counter exposed in the reliability metrics. Prior: a single malformed payload killed the subscriber until manual restart with no operator signal.

- **Critical alerters actually fire (OBS-1).** `temperature_alert` and `co2_alert` are now called from `engine._check_safety_thresholds` when readings breach phase ceilings by a safety margin (`temp_max_f + 5°F` / `co2_max_ppm + 1000ppm`). `contamination_alert` fires from `vision.analyze_frame_claude` when Claude reports `contamination_detected`. A new 60-second `_node_liveness_sweeper` in the lifespan task flips stale `hardware_nodes.status` to `offline` and calls `node_offline` once per outage (900s `last_seen` threshold). Prior: all of these alerters were defined but never called from anywhere in the codebase.

- **Retention rollup can't lose raw rows (DATA-3).** `_rollup_telemetry_5min / hourly`, `_rollup_weather_hourly`, and `_cleanup_old_rollups` now use `INSERT ... ON CONFLICT DO UPDATE` with weighted-mean merging (`(old_avg * old_count + new_avg * new_count) / total_count`; `MIN` / `MAX` kept monotonic; counts summed). Each rollup runs inside an explicit `BEGIN` / `COMMIT` / `ROLLBACK` block. Prior `INSERT OR IGNORE` + `DELETE` would delete raw rows that never made it into the aggregate when a retried run hit a pre-existing rollup row.

- **Cloud queue actually drops the oldest message on overflow (DATA-2).** `forward_telemetry` now `get_nowait()`s the stalest item, `put_nowait`s the new one, and increments `_queue_drops`. Count exposed via `get_cloud_status()`. Prior `except QueueFull: pass` silently discarded the newest payload without logging.

### Changed

- **`AsyncAnthropic` everywhere.** `vision`, `transcript`, `builder`, `contamination`, and `experiments` services use `anthropic.AsyncAnthropic(...)` with `await client.messages.create(...)`. Inline `import anthropic` hoisted to module top per AGENTS.md. Prior sync SDK froze the event loop for 3-15 seconds per Claude call, halting MQTT, telemetry, and Socket.IO during the freeze.

- **SQLite tuned for production.** `init_db` applies `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`. `get_db` re-applies connection-scoped pragmas on every acquisition. Referential integrity is now actually enforced — REFERENCES clauses were previously decorative.

- **`automation_firings` schema migration.** Added `status TEXT NOT NULL DEFAULT 'sent'` + `error TEXT` via `_add_column_if_missing`. New index on `status`. Historical rows remain readable as `status='sent'`.

- **`Settings.mqtt_username` / `mqtt_password` / `api_key`** — three new config fields. `.env.example` and `docker-compose.yml` plumbed accordingly.

- **`mqtt_publish` returns `bool`.** True when the publish landed, False when `_client is None` or the underlying publish raised. Callers can now tell success from silent drop.

- **Socket.IO `cors_allowed_origins="*"` is now explicitly justified in a comment** — the connect-handler auth check (`app.auth.socketio_auth_ok`) is the confidentiality gate. With `SPOREPRINT_API_KEY` unset, LAN attackers can still read telemetry via WS. Set the key to close that surface.

### Added

- `server/app/auth.py` — `ApiKeyMiddleware` + `socketio_auth_ok` bearer-token gate.
- `config/mosquitto/acl.conf` — per-role broker ACL (server has full authority; nodes restricted to their own namespace + `cmd/` read).
- `config/mosquitto/passwd.example` — placeholder with regen instructions.
- Reliability counters on `/api/health/detail/system.reliability`: `uptime_ts_clamps`, `mqtt_supervisor_restarts`.
- `server/tests/test_mqtt.py` — regression for the uptime-ts clamp.
- `server/tests/test_automation_fire.py` — regression for the rule-fire ordering (verifies `status='failed'` when the broker is down during publish).
- `test_override_persists_across_reload` — verifies overrides survive a simulated process restart.
- `_node_liveness_sweeper()` lifespan task (60s interval, 900s staleness threshold).

### Migration notes

- **Run `./setup.sh` after pulling.** It generates `SPOREPRINT_API_KEY` and the Mosquitto `server` credential in `.env` if they're blank. Nothing is overwritten.
- **Add MQTT creds to every firmware node before flashing v3.3.0.** Set `mqtt_user` / `mqtt_pass` in NVS (captive portal on first boot of a wiped device, or push via `ConfigStore`). Nodes without creds will fail to connect to the newly-authed broker.
- **Set a real OTA password on every node before it starts enforcing in v3.3.0 firmware.** Nodes running default `"sporeprint"` will refuse to call `ArduinoOTA.begin()` — they stay functional but cannot receive OTA updates until the operator sets a strong password.
- **Existing `manual_overrides` rows are now honored.** If you had rows in the table from a prior debug session, they will be loaded on next start. Clear any stale ones before upgrading if you don't want them applied.
