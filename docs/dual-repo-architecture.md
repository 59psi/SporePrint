# Dual-Repository Architecture

Open-source Pi-side core + private commercial cloud layer. The commercial repo consumes the open-source one as a git submodule, imports its React components directly via `@sporeprint/*` path aliases, and adds the cloud relay, mobile wrappers, and subscription / admin layer.

```mermaid
flowchart TB
    subgraph Public["PUBLIC · sporeprint · MIT License · github.com/59psi/SporePrint"]
        Server["Pi Server<br/>Python 3.11+ · FastAPI<br/>17 router groups · 106 endpoints<br/>SQLite · aiomqtt · Socket.IO<br/>Bearer-token gate (v3.3.0)"]
        Firmware["Firmware<br/>C++ · PlatformIO<br/>Climate · Relay · Lighting · Cam<br/>Auth'd MQTT + OTA pwd (v3.3.0)<br/>Offline buffer · Health reporting"]
        WebUI["Web UI<br/>React 18 · Vite · Tailwind v4<br/>15 pages · Zustand · Recharts<br/>Dashboard · Sessions · Species<br/>Automation · Analytics · Builder"]
    end

    subgraph Private["PRIVATE · sporeprint-cloud · Commercial Layer · Freemium"]
        Cloud["Cloud Backend<br/>Python · FastAPI · Socket.IO<br/>Relay · Auth · Push · AI<br/>Metrics · Subscriptions<br/>HMAC-signed commands (v3.3.1)<br/>Deployed on Railway"]
        Mobile["Mobile App<br/>Capacitor · iOS · Android<br/>Server discovery · offline cache<br/>Push notifications · IAP<br/>Premium features · Admin"]
        WebDesktop["Web Desktop<br/>18 desktop-optimized pages<br/>Split panes · Data tables<br/>KPI cards · Analytics charts<br/>Served at sporeprint.ai/app/"]
    end

    Private -.->|git submodule · @sporeprint/* imports| Public

    subgraph Services["External Services (all cloud-only)"]
        direction LR
        Supabase · Railway · RevenueCat · Firebase · Claude · Resend · Sentry · Cloudflare
    end

    Cloud --- Services

    classDef public fill:#1a2a1f,stroke:#3dd68c,color:#dfd;
    classDef private fill:#1a1f2a,stroke:#6b93d6,color:#ddf;
    classDef svc fill:#231a2a,stroke:#a06bd6,color:#e8d8ff;
    class Server,Firmware,WebUI public;
    class Cloud,Mobile,WebDesktop private;
    class Services svc;
```

## Tier model at the boundary

| Capability | Free | Premium ($4.99/mo · $39.99/yr) |
|---|---|---|
| Local HTTP + LAN access | Full control | Full control |
| Remote access | Tailscale (self-setup) | Cloud relay (zero-config, HMAC-signed) |
| Remote control | Read-only | Full control |
| Push notifications | ntfy (local LAN) | Native APNs + FCM |
| AI vision | None | Claude-powered (budget-capped) |
| Grow Advisor | — | Premium-only |

## Repo coupling contract

- The private repo **pins** a specific public-repo SHA via `.gitmodules`. Bumping it is an explicit `git add sporeprint/` + commit, never a floating pointer.
- The private repo **imports** (does not fork) React UI components from the submodule. Bug fixes in the public repo propagate to the mobile app on submodule update.
- The private repo **never modifies** submodule files. If a cloud feature needs a public-repo change, it lands there first, then the pointer bumps.
- The public-repo tests (`cd sporeprint/server && pytest`) must stay green after any private-repo-driven public change — enforced by CI + the release checklist.

## What lives where

| Concern | Public (sporeprint) | Private (sporeprint-cloud) |
|---|---|---|
| Telemetry ingest | ✅ mqtt.py + aiosqlite | — |
| Automation engine | ✅ (safety watchdog, overrides, rules) | — |
| Local UI (React components) | ✅ (imported via aliases) | — |
| Vision stub + Claude via Pi | ✅ | — |
| Mobile shell (Capacitor) | — | ✅ |
| Cloud relay + Socket.IO rooms | — | ✅ |
| Auth (Supabase JWT verify) | — | ✅ |
| Subscriptions (RevenueCat + Stripe) | — | ✅ |
| Admin (overrides, promos, broadcasts) | — | ✅ |
| Desktop web pages | — | ✅ (18 pages in `app/src/pages/web/`) |
| ESP32 firmware | ✅ | — |
| Cloud HMAC command signing | verify side | sign side (both at v3.3.1) |
