# Changelog

All notable changes to the public SporePrint Pi-side repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.3.0] - 2026-04-17

Security + stability release closing every critical finding from an external code audit. **Upgrading is strongly recommended for any Pi running unattended.**

### Security

- **MQTT broker is no-anonymous by default.** `config/mosquitto/mosquitto.conf` now sets `allow_anonymous false`, a `password_file`, and a per-role `acl.conf`. `setup.sh` provisions the `server` credential on first run (random 40-char). Firmware nodes read their credentials from NVS via `MqttManager._connect` (`mqtt_user` / `mqtt_pass`). The broker is bound to `127.0.0.1` in `docker-compose.yml`; never expose port 1883 to the internet. Prior to this release, any device on the LAN could publish `sporeprint/relay-01/cmd/heater {state:"on",pwm:255}` directly to the broker and the relay would obey.

- **`/api/cloud/configure` requires a short-lived `configure_token`.** `/pair` now validates the 6-digit code (with an 8-attempt / 10-minute lockout) and issues a `configure_token` in the response. `/configure` rejects any request without a matching token, rejects values containing `\n` / `\r` / `=` (newline-injection defense), resolves the `.env` path from the package root (not process CWD, which `/` under systemd), and writes atomically via `tempfile + os.replace` with `chmod 600`. Prior: unauthenticated LAN POST could rewrite `.env` and plant arbitrary env vars on next restart.

- **Backend bearer-token auth (opt-in).** New `app/auth.py` `ApiKeyMiddleware` gates every `/api/*` route plus the Socket.IO `connect` handshake when `SPOREPRINT_API_KEY` is set. Whitelist: `/api/health`, `/api/cloud/pair`, `/api/cloud/pairing-code`. `setup.sh` generates a key on first run so fresh installs are authed by default. Closes free-Claude-billing exhaustion, API-key exfil-by-substitution on the settings router, and ntfy-topic hijack.

- **Vision upload path traversal closed.** `POST /api/vision/frame` validates `X-Node-Id` against `^[a-zA-Z0-9_-]{1,32}$` and asserts the resolved write path stays inside `vision_storage`. Prior: a header value of `../../etc/passwd_image` would attempt to break out of the storage dir.

- **Hardware command topic lockdown.** `POST /api/hardware/nodes/{id}/command` drops any caller-supplied `topic` field and constructs the topic server-side from the URL path. Channel must match the safe-charset regex.

- **Cloud command channel defense-in-depth.** `cloud/service.on_command` now requires `id` to be present and not replayed (LRU of 1024), validates `target` / `channel` against `^[a-zA-Z0-9_-]{1,64}$`, and rejects commands whose target is not a registered `hardware_nodes.node_id` or `smart_plugs.plug_id`.

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
