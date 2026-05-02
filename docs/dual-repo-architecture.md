# Dual-Repository Architecture

Open-source Pi-side core + private commercial cloud layer. The commercial repo consumes the open-source one as a git submodule and adds the cloud relay, mobile shell, browser cloud-web shell, and subscription / admin layer.

**v3.4 business-model clarification**: this public repo (the Pi side) is free, open-source AGPL-3.0. The private repo (cloud + mobile + cloud-web) is entirely a paid commercial product — `require_premium` (402 `subscription_required`) gates every cloud data endpoint, the cloud relay refuses free Socket.IO clients, and the cloud-web edge middleware redirects free users to `/pricing?upsell=1`. That doesn't change anything about the Pi's behavior or the git-submodule coupling documented below. It does mean that if you're running the Pi standalone without a commercial subscription, the "commercial layer" half of this diagram is invisible to you — and that's a supported configuration.

**v4 layout shift on the private side**: the private cloud + mobile + browser surfaces now live in a pnpm monorepo at `frontend/packages/{cloud-web,mobile,pi-ui,design}/`. The cloud-web package is a Next.js 15 App Router app that ships **inside the same Railway service and Docker image** as the FastAPI cloud (`cloud/`). There is no `api.sporeprint.ai` subdomain and no separate Railway service — Next.js binds to `$PORT` and proxies `/api/*`, `/socket.io/*`, `/health/*`, `/docs/*`, `/firmware/*`, `/subscriptions/*`, `/webhooks/*` to FastAPI on internal `127.0.0.1:9000`. From this Pi-side repo's perspective, none of that matters: the cloud connector still talks to `https://sporeprint.ai`.

```mermaid
flowchart TB
    subgraph Public["PUBLIC · sporeprint · MIT License · github.com/59psi/SporePrint"]
        Server["Pi Server<br/>Python 3.11+ · FastAPI<br/>17 router groups · 106 endpoints<br/>SQLite · aiomqtt · Socket.IO<br/>Bearer-token gate (v3.3.0)"]
        Firmware["Firmware<br/>C++ · PlatformIO<br/>Climate · Relay · Lighting · Cam<br/>Auth'd MQTT + OTA pwd (v3.3.0)<br/>Offline buffer · Health reporting"]
        WebUI["Web UI<br/>React 18 · Vite · Tailwind v4<br/>15 pages · Zustand · Recharts<br/>Dashboard · Sessions · Species<br/>Automation · Analytics · Builder"]
    end

    subgraph Private["PRIVATE · sporeprint-cloud · Commercial Layer · Paid"]
        Cloud["Cloud Backend (FastAPI + Socket.IO)<br/>Relay · Auth · Push · AI<br/>Metrics · Subscriptions<br/>HMAC-signed commands (v3.3.1)<br/>Deployed on Railway (internal :9000)"]
        CloudWeb["Cloud-Web (Next.js 15 App Router)<br/>Server-rendered React<br/>Edge tier middleware<br/>Stripe Checkout · Web push (VAPID)<br/>Same Railway image, public on $PORT"]
        Mobile["Mobile App (Capacitor)<br/>iOS · Android<br/>Server discovery · offline cache<br/>FCM push · RevenueCat IAP<br/>frontend/packages/mobile/"]
    end

    Private -.->|git submodule + speciesProfiles auto-export| Public

    subgraph Services["External Services (all cloud-only)"]
        direction LR
        Supabase · Railway · RevenueCat · Firebase · Claude · Resend · Sentry · Cloudflare
    end

    Cloud --- Services

    classDef public fill:#1a2a1f,stroke:#3dd68c,color:#dfd;
    classDef private fill:#1a1f2a,stroke:#6b93d6,color:#ddf;
    classDef svc fill:#231a2a,stroke:#a06bd6,color:#e8d8ff;
    class Server,Firmware,WebUI public;
    class Cloud,CloudWeb,Mobile private;
    class Services svc;
```

## Tier model at the boundary (v3.4+ / v4)

| Capability | Free (Pi self-host, OSS) | Subscription ($4.99/mo · $39.99/yr) |
|---|---|---|
| Pi software (this repo) | ✓ AGPL-3.0, run it yourself | ✓ |
| Pi's own web UI on LAN | ✓ Full control, no paygate | ✓ |
| Mobile app on LAN / Tailscale | ✓ **Read-only** (writes blocked by `guardWriteAction`) | ✓ Full control |
| Mobile app via cloud relay | ✗ | ✓ HMAC-signed commands |
| Cloud-web (`sporeprint.ai`) | ✗ Edge middleware redirects to `/pricing?upsell=1` | ✓ Full |
| Pair Pi to commercial cloud | ✗ (`/devices/pair` → 402) | ✓ |
| Push notifications | ntfy on the Pi (LAN) | Native FCM (mobile) + Web Push (browser) via cloud |
| AI vision + advisor on the Pi | ✓ BYOK (your own Anthropic key, stored on the Pi) | ✓ BYOK on-Pi OR cloud-managed |
| Cloud AI (`/ai/*`) | ✗ (`require_premium` returns 402) | ✓ rate-limited or BYOK for unlimited |
| Cultures / Experiments / Planner (cloud) | ✗ | ✓ (added in v4) |
| Analytics / export / historical data durability | ✗ | ✓ |

Key boundary: the Pi itself has **no paygate**. All paywalling lives in the commercial mobile app (`guardWriteAction` for mobile writes on LAN/Tailscale), the commercial cloud (`require_premium` for REST, `subscription_required` for relay Socket.IO), and the cloud-web edge middleware (`tier === 'premium'` check on every protected route). A Pi-only user never encounters any of those.

## Repo coupling contract

- The private repo **pins** a specific public-repo SHA via `.gitmodules`. Bumping it is an explicit `git add sporeprint/` + commit, never a floating pointer.
- **Lockstep version bumps**: the parent's `scripts/bump.sh` is the single authority — it edits `cloud/pyproject.toml` (the canonical version), `sporeprint/server/pyproject.toml`, `sporeprint/firmware/VERSION.txt`, and `sporeprint/ui/package.json` so every shipped artifact reports the same version. The Pi-side does not have its own `bump.sh`.
- **Pi UI source vs bundle**: the source lives in the parent at `frontend/packages/pi-ui/`; the compiled output lands in the submodule at `sporeprint/ui/dist/`. The submodule's `.gitignore` has an explicit `!ui/dist/` exception so the prebuilt bundle is committed. The Pi pulls the submodule and serves the bundle locally — no Node toolchain required on the Pi.
- The species library auto-syncs: `frontend/packages/design/src/data/speciesProfiles.ts` is auto-generated from `sporeprint/server/app/species/profiles.py` so the Pi remains the source of truth for the 55-entry library.
- The private repo **never modifies** submodule files in-place from cloud-side branches. Submodule edits land via a branch + PR inside `sporeprint/`, then the parent bumps the pointer via `scripts/bump.sh` and `scripts/sync-after-merge.sh` (the post-merge script reconciles the submodule SHA after GitHub's squash-merge rewrites).
- The public-repo tests (`cd sporeprint/server && pytest`) must stay green after any private-repo-driven public change — enforced by CI + the release checklist.

## What lives where (v4)

| Concern | Public (sporeprint) | Private (sporeprint-cloud) |
|---|---|---|
| Telemetry ingest | ✅ mqtt.py + aiosqlite | — |
| Automation engine | ✅ (safety watchdog, overrides, rules) | — |
| Pi local UI source code | — | ✅ `frontend/packages/pi-ui/` (parent monorepo) |
| Pi local UI compiled bundle | ✅ `sporeprint/ui/dist/` (git-tracked via `!ui/dist/` exception) | builds into the submodule |
| Vision stub + Claude via Pi | ✅ | — |
| Mobile shell (Capacitor) | — | ✅ `frontend/packages/mobile/` |
| Cloud-web shell (Next.js 15) | — | ✅ `frontend/packages/cloud-web/` |
| Cloud relay + Socket.IO rooms | — | ✅ `cloud/app/relay/` |
| Auth (Supabase JWT verify) | — | ✅ |
| Subscriptions (RevenueCat mobile + Stripe web) | — | ✅ |
| Admin (overrides, promos, broadcasts) | — | ✅ |
| ESP32 firmware | ✅ | — |
| Cloud HMAC command signing | verify side | sign side (both at v3.3.1+) |
| OTA bundle signing (Ed25519) | verify on Pi | sign-side helpers in `sporeprint/scripts/` |
