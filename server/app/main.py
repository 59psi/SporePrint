import asyncio
import logging
import time
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Socket.IO accepts wildcard origins because engineio's CORS implementation only
# allows exact-string match (no regex/callable) and the Pi binds to a dynamic
# LAN IP that varies per-household. The gate is the connect-handler auth check
# (app.auth.socketio_auth_ok): when SPOREPRINT_API_KEY is set, every connect
# must present a matching bearer in the `auth` payload or the server rejects
# the handshake. Without the key an attacker reaching this WS can still read
# telemetry — treat `SPOREPRINT_API_KEY` as the actual confidentiality gate,
# not CORS.
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .db import init_db
    from .mqtt import start_mqtt
    from .species.service import seed_builtins

    from .automation.service import seed_builtin_rules
    from .cloud.service import start_cloud_connector
    from .retention.service import start_retention_task
    from .weather.service import start_weather_polling

    await init_db()
    await seed_builtins()
    await seed_builtin_rules()

    # Re-arm any safety watchdogs that were in-flight before the Pi restarted.
    # If an actuator's safety_max_on_seconds elapsed while the Pi was down,
    # rehydrate_safety_watchdogs publishes OFF immediately to get the device
    # back to a safe state.
    try:
        from .automation.engine import rehydrate_safety_watchdogs
        count = await rehydrate_safety_watchdogs()
        if count:
            logging.getLogger(__name__).info(
                "Rehydrated %d safety watchdog(s) from prior process", count
            )
    except Exception as e:
        logging.getLogger(__name__).warning("safety watchdog rehydration failed: %s", e)

    tasks = [
        asyncio.create_task(start_mqtt(sio)),
        asyncio.create_task(start_weather_polling(sio)),
        asyncio.create_task(start_retention_task()),
        asyncio.create_task(start_cloud_connector()),
        asyncio.create_task(_daily_retrain()),
        asyncio.create_task(_nightly_weather_aggregate()),
        asyncio.create_task(_node_liveness_sweeper()),
    ]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _daily_retrain():
    """Retrain prediction models daily at 4 AM (after retention runs at 3 AM)."""
    from .weather.prediction import retrain_models
    while True:
        try:
            now = time.time()
            next_4am = now - (now % 86400) + 4 * 3600
            if next_4am <= now:
                next_4am += 86400
            await asyncio.sleep(next_4am - now)
            await retrain_models()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logging.getLogger(__name__).error("Daily retrain failed: %s", e)
            await asyncio.sleep(3600)


async def _nightly_weather_aggregate():
    """Aggregate yesterday's weather data at 2 AM for the seasonal planner."""
    from .planner.service import aggregate_daily_weather
    while True:
        try:
            now = time.time()
            next_2am = now - (now % 86400) + 2 * 3600
            if next_2am <= now:
                next_2am += 86400
            await asyncio.sleep(next_2am - now)
            await aggregate_daily_weather()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logging.getLogger(__name__).error("Weather aggregate failed: %s", e)
            await asyncio.sleep(3600)


# A node is considered offline once we haven't heard from it for this long.
# Climate nodes publish every 60s + heartbeats every 5 min, so 15 min is three
# missed heartbeats — enough to discriminate a WiFi blip from a true outage.
_NODE_OFFLINE_THRESHOLD_SECONDS = 900
_NODE_SWEEPER_INTERVAL_SECONDS = 60


async def _node_liveness_sweeper():
    """Flag hardware nodes whose last_seen is too stale and page the operator once.

    Pages ntfy locally AND forwards the event to the cloud relay so premium
    mobile subscribers get a push notification when a node drops offline.
    """
    from .db import get_db
    from .notifications.service import node_offline
    from .cloud.service import forward_event
    log = logging.getLogger(__name__)

    while True:
        try:
            await asyncio.sleep(_NODE_SWEEPER_INTERVAL_SECONDS)
            now = time.time()
            threshold = now - _NODE_OFFLINE_THRESHOLD_SECONDS
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT node_id, last_seen FROM hardware_nodes
                       WHERE status != 'offline' AND last_seen IS NOT NULL AND last_seen < ?""",
                    (threshold,),
                )
                stale_rows = await cursor.fetchall()
                for row in stale_rows:
                    node_id = row["node_id"]
                    last_seen = row["last_seen"]
                    await db.execute(
                        "UPDATE hardware_nodes SET status = 'offline' WHERE node_id = ?",
                        (node_id,),
                    )
                    log.warning("Node %s marked offline (last_seen %.0fs ago)",
                                node_id, now - last_seen)
                    try:
                        await node_offline(node_id)
                    except Exception as e:
                        log.warning("node_offline notification failed for %s: %s", node_id, e)
                    try:
                        await forward_event("node_offline", {
                            "node_id": node_id,
                            "last_seen": last_seen,
                            "seconds_stale": now - last_seen,
                        })
                    except Exception as e:
                        log.warning("forward_event(node_offline) failed for %s: %s", node_id, e)
                if stale_rows:
                    await db.commit()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logging.getLogger(__name__).error("Node liveness sweeper failed: %s", e)
            await asyncio.sleep(60)


app = FastAPI(title="SporePrint", version="3.4.5", lifespan=lifespan)

# LAN-scoped CORS — the Pi is a local-network appliance, not an internet service.
#
# Threat model: a wildcard "*" origin would let ANY website the user visits
# toggle their fans, lights, and smart plugs via cross-origin requests.
# LAN-scoping blocks that entirely.
#
# Why we do NOT include sporeprint.ai:
#   1. Mixed content: the hosted web app runs on HTTPS. Browsers block HTTPS
#      pages from making HTTP requests to the Pi (http://192.168.x.x:3001).
#      CORS is not even consulted — the request is refused by the browser
#      before the preflight goes out.
#   2. NAT: Railway servers hosting sporeprint.ai cannot reach a Pi behind
#      a home router. There is no public reverse-FQDN pointing at the Pi.
#   3. Actual flow: device pairing and cloud/configure are only ever POSTed
#      from the mobile app (Capacitor native shell — no browser sandbox) or
#      from the web app running on LAN in dev mode (localhost:3002 → Pi).
#      Once paired, the Pi initiates an OUTBOUND WebSocket to the cloud —
#      cloud never initiates inbound to the Pi.
#
# Allowed origins:
#   - localhost / 127.0.0.1 (any port) — local browser dev + Pi itself
#   - *.local (mDNS, e.g. sporeprint.local) — zeroconf discovery
#   - RFC1918 private IPs (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) — LAN access
#   - capacitor://localhost — native iOS/Android shells
_LAN_ORIGIN_REGEX = (
    r"^(https?://)?("
    r"localhost|127\.0\.0\.1|"
    r"[a-zA-Z0-9-]+\.local|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$|^capacitor://localhost$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_LAN_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    allow_credentials=True,
)

from .auth import ApiKeyMiddleware, socketio_auth_ok

app.add_middleware(ApiKeyMiddleware)

from .telemetry.router import router as telemetry_router
from .sessions.router import router as sessions_router
from .species.router import router as species_router
from .hardware.router import router as hardware_router
from .automation.router import router as automation_router
from .vision.router import router as vision_router
from .transcript.router import router as transcript_router
from .builder.router import router as builder_router
from .builder.models_router import router as models_router
from .cloud.router import router as cloud_router
from .health.router import router as health_router
from .weather.router import router as weather_router
from .planner.router import router as planner_router
from .contamination.router import router as contamination_router
from .cultures.router import router as cultures_router
from .chambers.router import router as chambers_router
from .experiments.router import router as experiments_router
from .labels.router import router as labels_router
from .settings_router import router as settings_router

app.include_router(telemetry_router, prefix="/api/telemetry", tags=["telemetry"])
app.include_router(sessions_router, prefix="/api/sessions", tags=["sessions"])
app.include_router(species_router, prefix="/api/species", tags=["species"])
app.include_router(hardware_router, prefix="/api/hardware", tags=["hardware"])
app.include_router(automation_router, prefix="/api/automation", tags=["automation"])
app.include_router(vision_router, prefix="/api/vision", tags=["vision"])
app.include_router(transcript_router, prefix="/api/transcript", tags=["transcript"])
app.include_router(builder_router, prefix="/api/builder", tags=["builder"])
app.include_router(models_router, prefix="/api/builder", tags=["builder"])
app.include_router(weather_router, prefix="/api/weather", tags=["weather"])
app.include_router(cloud_router, prefix="/api/cloud", tags=["cloud"])
app.include_router(health_router, prefix="/api/health/detail", tags=["health"])
app.include_router(planner_router, prefix="/api/planner", tags=["planner"])
app.include_router(contamination_router, prefix="/api/contamination", tags=["contamination"])
app.include_router(cultures_router, prefix="/api/cultures", tags=["cultures"])
app.include_router(chambers_router, prefix="/api/chambers", tags=["chambers"])
app.include_router(experiments_router, prefix="/api/experiments", tags=["experiments"])
app.include_router(labels_router, prefix="/api/labels", tags=["labels"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.4.5"}


# Track Socket.IO clients for health reporting
from .health.service import track_client_connect, track_client_disconnect


@sio.on("connect")
async def _sio_connect(sid, environ, auth=None):
    # v3.3.3 — pass the remote address into the auth callback so its rate-limit
    # can kick in (see app.auth.socketio_auth_ok docstring for the LAN-trust
    # rationale). environ['REMOTE_ADDR'] is set by uvicorn's ASGI layer.
    _log = logging.getLogger(__name__)
    remote_addr = environ.get("REMOTE_ADDR") or environ.get("HTTP_X_FORWARDED_FOR")
    if not socketio_auth_ok(auth, remote_addr=remote_addr):
        _log.warning("Socket.IO connect refused: sid=%s remote=%s", sid, remote_addr or "?")
        return False
    track_client_connect(sid, environ)
    _log.info("Socket.IO connect: sid=%s remote=%s", sid, remote_addr or "?")


@sio.on("disconnect")
async def _sio_disconnect(sid):
    track_client_disconnect(sid)


socket_app = socketio.ASGIApp(sio, app)
