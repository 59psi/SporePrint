# Dual-Repository Architecture

Open-source Pi-side core + private commercial cloud layer. The commercial repo consumes the open-source one as a git submodule, imports its React components directly via `@sporeprint/*` path aliases, and adds the cloud relay, mobile wrappers, and subscription / admin layer.

**v3.4 business-model clarification**: this public repo (the Pi side) is free, open-source AGPL-3.0. The private repo (cloud + mobile + web app) is now entirely a paid commercial product — `require_premium` (402 `subscription_required`) gates every cloud data endpoint, and the cloud relay refuses free Socket.IO clients. That doesn't change anything about the Pi's behavior or the git-submodule coupling documented below. It does mean that if you're running the Pi standalone without a commercial subscription, the "commercial layer" half of this diagram is invisible to you — and that's a supported configuration.

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

## Tier model at the boundary (v3.4+)

| Capability | Free (Pi self-host, OSS) | Subscription ($4.99/mo · $39.99/yr) |
|---|---|---|
| Pi software (this repo) | ✓ AGPL-3.0, run it yourself | ✓ |
| Pi's own web UI on LAN | ✓ Full control, no paygate | ✓ |
| Mobile app on LAN / Tailscale | ✓ **Read-only** (writes blocked by `guardWriteAction` in the commercial mobile app) | ✓ Full control |
| Mobile app via cloud relay | ✗ | ✓ HMAC-signed commands |
| Web app (`sporeprint.ai/app`) | ✗ Paywalled shell: `/account` + `/pricing` + `/docs/*` only | ✓ Full |
| Pair Pi to commercial cloud | ✗ (`/devices/pair` → 402) | ✓ |
| Push notifications | ntfy on the Pi (works on LAN) | Native APNs + FCM via cloud |
| AI vision + advisor on the Pi | ✓ BYOK (your own Anthropic key, stored on the Pi) | ✓ BYOK on-Pi OR cloud-managed |
| Cloud AI (`/ai/*`) | ✗ (`require_premium` returns 402) | ✓ rate-limited or BYOK for unlimited |
| Analytics / export / historical data durability | ✗ | ✓ |

Key boundary: the Pi itself has **no paygate**. All paywalling lives in the commercial mobile app (`guardWriteAction` for mobile writes on LAN/Tailscale) and the commercial cloud (`require_premium` for REST, `subscription_required` for relay Socket.IO). A Pi-only user never encounters any of those.

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
