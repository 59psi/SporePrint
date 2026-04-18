# Changelog

All notable changes to the public SporePrint Pi-side repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
