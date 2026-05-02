# Data Flow

How data moves through the SporePrint system across its four main flows: sensor telemetry, weather intelligence, user actions, and the closed-loop hardware control path.

> **Cloud-side context (v4)**: from the Pi's perspective, nothing about these flows changed. The cloud upgraded its public surface from a Vite SPA at `/app/*` to a Next.js 15 App Router app at `/`, both running on the same Railway service that has always handled the Pi's cloud connector. Telemetry / commands / heartbeats still hit the same `https://sporeprint.ai` Socket.IO endpoint.

```mermaid
flowchart TB
    subgraph TelemetryFlow["① Telemetry Flow (sensor → storage → consumers)"]
        ESP["ESP32 Sensors<br/>SHT31 · SCD41 · BH1750"]
        Mosq["Mosquitto<br/>auth'd broker (v3.3.0)"]
        PiSrv["Pi Server<br/>FastAPI · mqtt._handle_message<br/>uptime-ts clamp (v3.3.0)"]
        SQLite["SQLite<br/>26 tables · WAL mode<br/>foreign_keys ON (v3.3.0)"]
        Retention["Retention rollup<br/>3am · weighted-merge upsert"]
        SIO["Socket.IO"]
        WebUI["Web UI<br/>Live telemetry"]
        Ntfy["ntfy<br/>Local push"]

        ESP -->|MQTT publish| Mosq
        Mosq --> PiSrv
        PiSrv --> SQLite
        PiSrv --> SIO
        PiSrv --> Ntfy
        SIO --> WebUI
        SQLite --> Retention
        Retention --> SQLite
    end

    subgraph WeatherFlow["② Weather + Intelligence"]
        WeatherAPI["Weather Providers<br/>Open-Meteo · OWM · NWS"]
        Forecast["Forecast Engine<br/>Pressure correlation<br/>Risk scoring"]
        Prediction["Prediction Model<br/>72h indoor temp"]
        Planner["Planner / Wizard<br/>Recommendations<br/>Automation hints"]

        WeatherAPI --> Forecast
        Forecast --> Prediction
        Prediction --> Planner
    end

    subgraph UserFlow["③ User Action Flow"]
        User["User Actions<br/>Configure · Control · View"]
        REST["REST API<br/>106 endpoints · 17 routers<br/>Bearer: SPOREPRINT_API_KEY"]
        Sessions["Session Manager"]
        Auto["Automation Engine<br/>+ safety_max_on_seconds (v3.3.0)"]
        Vision["Vision Pipeline<br/>AsyncAnthropic (v3.3.0)"]
        MQTTCmd["MQTT Commands<br/>sporeprint/<node>/cmd/<ch>"]
        Claude["Anthropic Claude"]

        User -->|HTTP + bearer| REST
        REST --> Sessions
        REST --> Auto
        REST --> Vision
        Auto --> MQTTCmd
        MQTTCmd --> ESP
        Vision --> Claude
    end

    subgraph ControlLoop["④ Hardware Control Loop (closed-loop)"]
        Sense["Sensor Read<br/>every 10 s"]
        Eval["Evaluate Rules<br/>threshold + schedule"]
        Compute["Compute Action<br/>pwm · duration · ramp"]
        Publish["MQTT Publish"]
        Actuate["Actuate<br/>Fan · Heat · Mist · Light"]
        Log["automation_firings<br/>status: pending→sent/failed<br/>(v3.3.0 audit fix)"]

        Sense --> Eval
        Eval --> Compute
        Compute --> Log
        Log --> Publish
        Publish --> Actuate
        Actuate -.->|next cycle| Sense
    end

    classDef hw fill:#2a241a,stroke:#d9a441,color:#ffd;
    classDef svc fill:#1a2a1f,stroke:#3dd68c,color:#dfd;
    classDef store fill:#1a1f2a,stroke:#6b93d6,color:#ddf;
    classDef loop fill:#231a2a,stroke:#a06bd6,color:#e8d8ff;
    class ESP,Actuate hw;
    class Mosq,PiSrv,REST,Sessions,Auto,Vision,MQTTCmd,SIO,Ntfy,Retention svc;
    class SQLite,Claude,WeatherAPI store;
    class Sense,Eval,Compute,Publish,Log loop;
```

## Notable v3.3.x changes visible in the data flow

- **Telemetry ts clamp** — `mqtt._handle_message` treats any `ts < 2020-01-01` as firmware uptime-seconds and replaces it with server time. Prevents 1970-epoch rows from offline-buffer drain.
- **Retention rollup upsert** — `INSERT ... ON CONFLICT DO UPDATE` with weighted-mean merging replaces the old `INSERT OR IGNORE + DELETE` (which could lose raw rows on partial retries).
- **Rule-fire audit ordering** — firings are now written `status='pending'` → publish → `status='sent'|'failed'`. The audit log no longer lies during MQTT reconnect windows.
- **`safety_max_on_seconds` watchdog** — when an ON publish succeeds for a rule with a non-zero max, a cancellable auto-off task arms. Prevents stuck-on heaters.
- **`AsyncAnthropic` on Pi** — vision, transcript, builder, contamination, experiments all await Claude calls. Prior sync SDK froze the event loop 3-15 s per call.
- **Auth'd MQTT broker** — `allow_anonymous false`, credentials in NVS on every node. Previously the broker on 1883 would accept any publisher.

## Notable v4.0.0 changes visible in the data flow

- **OTA progress emit** — `ota.py::_emit_step()` now calls `forward_event("ota_step", payload)` per phase (`downloading` / `verifying` / `promoting` / `restarting` / `healthy` / `failed`), so the cloud + mobile + browser can render a real OTA progress bar. `_promote_and_restart` was split into `_promote` + `_restart_unit` for recoverability.
- **Firmware coredump partition** — `firmware/partitions.csv` adds a 64 KB coredump slot at `0x3F0000`. `coredump.{h,cpp}` (`isPresent / readChunked / erase / uploadIfPresent`) is called from each node's `setup()` so a crashed boot ships its coredump once Wi-Fi + MQTT are up, then erases it.
- **Firmware log forwarding ring buffer** — `log_forward.{h,cpp}` exposes `SP_LOG()` backed by a 32-entry × 200-byte ring drained over MQTT. Lets us see what a node logged in the seconds before a crash without an attached serial cable.
- **OTA bundle signatures** — Ed25519 helpers in the submodule's `scripts/`: `generate-ota-keypair.py` mints the keypair, `sign-ota-bundle.py` signs each shipped bundle. Cloud verifies before promotion; Pi verifies during `_promote`.
- **Lockstep version bump** — Pi server / firmware / Pi UI / cloud all carry `4.0.0` simultaneously. The protocol surface against pre-v4 clouds is unchanged; the bump is bookkeeping for the parent monorepo's release cadence.
