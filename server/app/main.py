import asyncio
import datetime as dt
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ._request_id_mw import RequestIdMiddleware
from .auth import ApiKeyMiddleware, socketio_auth_ok, socketio_client_addr
from .cloud.service import forward_event
from .cloud.session_sync import attach as attach_session_sync
from .config import settings
from .db import get_db
from .hardware.coredumps import coredump_dir, discard_partial_writes
from .health.service import (
    register_task,
    track_client_connect,
    track_client_disconnect,
    update_task,
)
from .host_allow import CrossSiteRequestGuard, HostAllowMiddleware, socketio_origin_allowed
from .notifications.service import node_offline
from .retention import service as retention_service
from .sessions.service import check_phase_reminders, release_cold_storage_links
from .settings_service import apply_persisted_settings

# Socket.IO checks a browser's Origin with host_allow.socketio_origin_allowed:
# the request's own host, or a name the Host allow-list admits. A page on
# another site can neither open the live stream nor read it (the Pi's LAN
# address varies per household, so an exact-origin list cannot work). Native
# clients send no Origin and pass. With SPOREPRINT_API_KEY set, every connect
# must also present the bearer (the connect handler's app.auth.socketio_auth_ok).
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=socketio_origin_allowed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .config import settings
    from .db import init_db
    from .logging_config import configure as configure_logging
    from .mqtt import start_mqtt
    from .species.service import seed_builtins

    from .automation.service import seed_builtin_rules
    from .cloud.service import start_cloud_connector
    from .retention.service import start_retention_task
    from .weather.service import start_weather_polling

    # Configure structured logging with request_id
    # threading before anything else so even boot-path messages carry
    # the contextvar (empty on boot; non-empty per-request).
    configure_logging()

    log = logging.getLogger(__name__)

    # Fail loudly if api_key is unset. allow_unauthenticated must be
    # explicitly true for the server to boot without an API key — the
    # previous behavior silently ran in LAN-trust mode, which is fine on
    # an isolated network but dangerous if the Pi is ever port-forwarded
    # or reachable from untrusted WiFi.
    if not settings.api_key:
        if not settings.allow_unauthenticated:
            raise RuntimeError(
                "SPOREPRINT_API_KEY is empty and SPOREPRINT_ALLOW_UNAUTHENTICATED=false. "
                "On a Pi, run ./install.sh (it sets up LAN-trust mode for the bundled "
                "dashboard); otherwise set SPOREPRINT_API_KEY to require a bearer "
                "token, or set SPOREPRINT_ALLOW_UNAUTHENTICATED=true for intentional "
                "LAN-trust mode on an isolated network."
            )
        log.warning(
            "SPOREPRINT_API_KEY is empty — running in LAN-trust mode with no auth. "
            "Any host that can reach this server can read telemetry and issue commands."
        )

    await init_db()
    # The operator's saved settings (Claude key, ntfy topic, OTA verify key,
    # weather location) into the runtime config before anything reads it.
    await apply_persisted_settings()
    _ensure_coredump_dir(log)
    await seed_builtins()
    await seed_builtin_rules()
    # A grow that went to cold storage before advancing there dropped its
    # chamber link still holds the chamber it left; release it before the
    # rules engine starts on that chamber's telemetry.
    await release_cold_storage_links()

    # The task registry. Each
    # long-running supervisor registers on boot and reports running / idle /
    # error (with the error) from its own loop, so GET
    # /api/health/detail/tasks shows a failing job as failing. The cloud
    # connector reports through app.cloud.service.get_task_status instead.
    register_task("mqtt", "running")
    register_task("weather_polling", "idle")
    register_task("retention", "idle")
    register_task("daily_retrain", "idle")
    register_task("nightly_weather_aggregate", "idle")
    register_task("node_liveness_sweeper", "idle")
    register_task("phase_reminders", "idle")

    from .integrations._health_sweeper import (
        run_health_sweeper,
        push_state_snapshot,
    )

    # Grow sessions → cloud on every change and every (re)connect.
    attach_session_sync()

    tasks = [
        asyncio.create_task(start_mqtt(sio)),
        asyncio.create_task(start_weather_polling(sio)),
        asyncio.create_task(start_retention_task()),
        asyncio.create_task(start_cloud_connector()),
        asyncio.create_task(_daily_retrain()),
        asyncio.create_task(_nightly_weather_aggregate()),
        asyncio.create_task(_node_liveness_sweeper()),
        asyncio.create_task(_phase_reminder_loop()),
        # v4.1.5 — emit vendor_health_degraded events on transitions
        # so the cloud's push-rules + escalation chains can fire.
        asyncio.create_task(run_health_sweeper()),
    ]

    # Re-arm any safety watchdogs that were in-flight before the Pi restarted.
    # Runs after start_mqtt is scheduled: every row (including one that expired
    # while the Pi was down) becomes a watchdog task that sends its OFF over the
    # actuator's own transport, retrying until MQTT / the vendor drivers are up,
    # and deletes the row only once the OFF actually went out.
    try:
        from .automation.engine import rehydrate_safety_watchdogs
        count = await rehydrate_safety_watchdogs()
        if count:
            log.info("Rehydrated %d safety watchdog(s) from prior process", count)
    except Exception as e:
        log.warning("safety watchdog rehydration failed: %s", e)

    # v4.1 integrations — boot every driver persisted as enabled. Failures
    # are isolated per-driver in the registry so a misconfigured Aranet
    # base station can't take down the Pi.
    await _start_enabled_integrations()
    # v4.1.5 — push the initial snapshot so the cloud's fleet cache warms up
    # immediately. forward_event does NOT queue: if the connector's socket is
    # not up yet this push is dropped, which is harmless because the connector
    # re-pushes the snapshot on every (re)connect.
    await push_state_snapshot()
    # Last, once MQTT (the rules engine), the re-armed safety watchdogs and
    # the vendor drivers are all running: the one-time auto_vacuum rewrite.
    await _convert_to_incremental_auto_vacuum(log)
    yield
    await _stop_all_integrations()
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
    from .health.service import update_task
    while True:
        try:
            now = time.time()
            next_4am = now - (now % 86400) + 4 * 3600
            if next_4am <= now:
                next_4am += 86400
            await asyncio.sleep(next_4am - now)
            update_task("daily_retrain", "running")
            await retrain_models()
            update_task("daily_retrain", "idle")
        except asyncio.CancelledError:
            return
        except Exception as e:
            update_task("daily_retrain", "error", error=str(e))
            logging.getLogger(__name__).error("Daily retrain failed: %s", e)
            await asyncio.sleep(3600)


async def _nightly_weather_aggregate():
    """Aggregate yesterday's weather data at 2 AM for the seasonal planner."""
    from .planner.service import aggregate_daily_weather
    from .health.service import update_task
    while True:
        try:
            now = time.time()
            next_2am = now - (now % 86400) + 2 * 3600
            if next_2am <= now:
                next_2am += 86400
            await asyncio.sleep(next_2am - now)
            update_task("nightly_weather_aggregate", "running")
            await aggregate_daily_weather()
            update_task("nightly_weather_aggregate", "idle")
        except asyncio.CancelledError:
            return
        except Exception as e:
            update_task("nightly_weather_aggregate", "error", error=str(e))
            logging.getLogger(__name__).error("Weather aggregate failed: %s", e)
            await asyncio.sleep(3600)


def _ensure_coredump_dir(log: logging.Logger) -> None:
    """Create the node coredump directory at boot and say if it is unusable.

    Dumps are reassembled there when a node reports a panic; finding out it
    is unwritable only then means that dump is lost.
    """
    path = coredump_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error("Coredump directory %s cannot be created: %s — node panic "
                  "dumps will be lost", path, e)
        return
    if not os.access(path, os.W_OK | os.X_OK):
        log.error("Coredump directory %s is not writable — node panic dumps "
                  "will be lost", path)
        return
    # A crash mid-write leaves a temp file; that upload was never
    # acknowledged, so the node still holds the dump and sends it again.
    removed = discard_partial_writes()
    if removed:
        log.info("Removed %d partially written coredump file(s)", removed)


# The one-time auto_vacuum conversion is a full VACUUM: it rewrites the whole
# file while holding the write lock. Up to this size that is seconds on a Pi
# SD card. A bigger database is left to the nightly retention window, which
# converts once a large share of the file is free (retention._vacuum), rather
# than stalling MQTT ingest and rule writes for minutes after every upgrade.
_BOOT_AUTO_VACUUM_MAX_BYTES = 32 * 1024 * 1024


async def _convert_to_incremental_auto_vacuum(log: logging.Logger) -> None:
    """Switch a small existing database to auto_vacuum=INCREMENTAL at boot.

    Called at the END of startup: MQTT (the rules engine), the rehydrated
    safety watchdogs and the vendor drivers are already running, so a
    persisted safety ceiling is re-armed (or tripped) before the rewrite, not
    after it. New databases are created incremental, so this is a no-op for
    them. A failure (e.g. disk full) is logged and boot continues — the
    nightly job only loses its ability to hand freed pages back.
    """
    try:
        try:
            size = Path(settings.database_path).stat().st_size
        except OSError:
            size = 0
        if size <= _BOOT_AUTO_VACUUM_MAX_BYTES:
            await retention_service.ensure_incremental_auto_vacuum()
            return
        async with get_db() as db:
            mode = await retention_service._pragma_int(db, "PRAGMA auto_vacuum")
        if mode != retention_service._AUTO_VACUUM_INCREMENTAL:
            log.info(
                "Database is %.0f MB and not in auto_vacuum=INCREMENTAL mode; "
                "leaving the one-time conversion VACUUM to the nightly retention "
                "window instead of stalling writers at boot", size / 1e6,
            )
    except Exception as e:
        log.error("auto_vacuum conversion failed; continuing boot: %s", e)


# Overdue-phase reminders (INFO) go out once a day at this local hour
# (container time: UTC unless TZ is set). Daily rather than hourly: the INFO
# tier's dedup is 1 h, so an hourly check would nag every hour for days.
_PHASE_REMINDER_LOCAL_HOUR = 9


def _seconds_until_next_phase_reminder(now: float | None = None) -> float:
    now = time.time() if now is None else now
    current = dt.datetime.fromtimestamp(now)
    target = current.replace(hour=_PHASE_REMINDER_LOCAL_HOUR, minute=0,
                             second=0, microsecond=0)
    if target <= current:
        target += dt.timedelta(days=1)
    return target.timestamp() - now


async def _phase_reminder_loop():
    """Nudge the operator about active sessions that have overrun their phase."""
    log = logging.getLogger(__name__)
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_phase_reminder())
            update_task("phase_reminders", "running")
            sent = await check_phase_reminders()
            update_task("phase_reminders", "idle")
            if sent:
                log.info("Sent %d overdue-phase reminder(s)", sent)
        except asyncio.CancelledError:
            return
        except Exception as e:
            update_task("phase_reminders", "error", error=str(e))
            log.error("Phase reminder check failed: %s", e)


# A node is considered offline once we haven't heard from it for this long.
# last_seen is refreshed by heartbeats, live status frames and every telemetry
# frame (mqtt.py). Heartbeats come at least every 5 min (current firmware
# keeps them on their own clock) and relay banks report switch state every
# 60 s, so 15 min is three missed heartbeats — enough to tell a WiFi blip from
# an outage (and a planned reconnect, such as a transport switch, from either).
_NODE_OFFLINE_THRESHOLD_SECONDS = 900
_NODE_SWEEPER_INTERVAL_SECONDS = 60


async def _sweep_stale_nodes(now: float | None = None) -> list[dict]:
    """Mark the nodes silent past the threshold offline and page each one once.

    Paged once per silence, whatever set status='offline': the broker's LWT
    does that ~22 s into nearly every real outage (power or WiFi loss, a crash
    loop), and the old `status != 'offline'` filter skipped exactly those
    nodes, so they were never paged. offline_notified_at marks the page; the
    node's next heartbeat or live 'online' status clears it (mqtt.py), and it
    survives a Pi restart, so a dead node is not paged again at every boot.

    The rows are committed before any page goes out: the ntfy POST (5 s
    timeouts) used to run inside the open write transaction, and telemetry
    ingest and rule firings meanwhile failed with 'database is locked'.
    Pages ntfy locally, tells local Socket.IO clients (node_status) and
    forwards node_offline to the cloud relay, which pushes premium mobile
    subscribers.
    """
    log = logging.getLogger(__name__)
    now = time.time() if now is None else now
    threshold = now - _NODE_OFFLINE_THRESHOLD_SECONDS
    async with get_db() as db:
        cursor = await db.execute(
            """UPDATE hardware_nodes SET status = 'offline', offline_notified_at = ?
                WHERE offline_notified_at IS NULL
                  AND last_seen IS NOT NULL AND last_seen < ?
            RETURNING node_id, last_seen""",
            (now, threshold),
        )
        stale = [dict(row) for row in await cursor.fetchall()]
        await db.commit()

    for row in stale:
        node_id, last_seen = row["node_id"], row["last_seen"]
        log.warning("Node %s marked offline (last_seen %.0fs ago)", node_id, now - last_seen)
        try:
            await sio.emit("node_status", {"node_id": node_id, "status": "offline"})
        except Exception as e:
            log.warning("node_status emit failed for %s: %s", node_id, e)
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
    return stale


async def _node_liveness_sweeper():
    """Once a minute, page the nodes that went silent (_sweep_stale_nodes)."""
    log = logging.getLogger(__name__)
    while True:
        try:
            await asyncio.sleep(_NODE_SWEEPER_INTERVAL_SECONDS)
            update_task("node_liveness_sweeper", "running")
            await _sweep_stale_nodes()
            update_task("node_liveness_sweeper", "idle")
        except asyncio.CancelledError:
            return
        except Exception as e:
            update_task("node_liveness_sweeper", "error", error=str(e))
            log.error("Node liveness sweeper failed: %s", e)
            await asyncio.sleep(60)


app = FastAPI(title="SporePrint", version="5.2.4", lifespan=lifespan)

# LAN-scoped CORS — the Pi is a local-network appliance, not an internet service.
#
# Threat model: a wildcard "*" origin would let ANY website the user visits
# read the API's answers and, with JSON bodies, toggle their fans, lights and
# smart plugs. CORS only governs what a page may read and which requests need
# a preflight: a page can still SEND a body-less or form POST. Those are
# refused by host_allow.CrossSiteRequestGuard (wrapped around this app in
# socket_app) unless their Origin is a name the Pi answers to.
#
# Why we do NOT include sporeprint.ai:
#   1. Mixed content: the hosted web app runs on HTTPS. Browsers block HTTPS
#      pages from making HTTP requests to the Pi (http://192.168.x.x:3001).
#      CORS is not even consulted — the request is refused by the browser
#      before the preflight goes out.
#   2. The cloud never calls the Pi from a browser. Its only calls in are
#      pairing's pair-verify and configure, server to server through the
#      operator's temporary public address, with no Origin; once paired, the
#      Pi keeps an OUTBOUND WebSocket to the cloud relay.
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

# Each add_middleware wraps the ones added before it, so the request passes
# RequestIdMiddleware -> CORSMiddleware -> ApiKeyMiddleware -> the routes. The
# API-key 401 thus goes back out through CORS: a cross-origin client reads a
# 401 instead of an opaque CORS failure. The request id is outermost, so a
# rejected request still carries a correlatable id.
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_LAN_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin",
                   "X-Requested-With", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    allow_credentials=True,
)
app.add_middleware(RequestIdMiddleware)

from .telemetry.router import router as telemetry_router
from .sessions.router import router as sessions_router
from .species.router import router as species_router
from .hardware.router import router as hardware_router
from .automation.router import router as automation_router
# V2-1 — hardware-coverage verdict lives under /api/chambers/{id}/... but is an
# automation concern, so its router ships from the automation package.
from .automation.coverage_router import router as automation_coverage_router
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
from .provision import router as provision_router
from .integrations import router as integrations_router
from .integrations import actions_router as integrations_actions_router
from .integrations._registry import (
    start_enabled_drivers as _start_enabled_integrations,
    stop_all_drivers as _stop_all_integrations,
)
from .integrations.grafana.router import router as grafana_metrics_router
from .integrations.aranet.router import router as aranet_extra_router
from .integrations.pulse.router import router as pulse_extra_router

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
# V2-1 — GET /api/chambers/{id}/automation-coverage?species=... (extra segment,
# so it does not collide with the chambers_router's /{chamber_id} routes).
app.include_router(automation_coverage_router, prefix="/api/chambers", tags=["automation.coverage"])
app.include_router(experiments_router, prefix="/api/experiments", tags=["experiments"])
app.include_router(labels_router, prefix="/api/labels", tags=["labels"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(provision_router, prefix="/api/provision", tags=["provision"])
app.include_router(integrations_router, prefix="/api/integrations", tags=["integrations"])
# v4.1.2 — vendor write-action dispatcher. Same /api/integrations
# prefix; routes are /{slug}/actions and /{slug}/actions/{action}.
app.include_router(
    integrations_actions_router,
    prefix="/api/integrations",
    tags=["integrations.actions"],
)
# Grafana exporter — mounted at /metrics (outside /api/* so the api-key
# middleware does not gate it; bearer-token auth is configured per-driver).
app.include_router(grafana_metrics_router, tags=["integrations.grafana"])
# Aranet extras — /api/integrations/aranet/discover for the settings UI.
app.include_router(
    aranet_extra_router, prefix="/api/integrations/aranet", tags=["integrations.aranet"]
)
# Pulse Grow extras — /api/integrations/pulse/devices for the settings UI.
app.include_router(
    pulse_extra_router, prefix="/api/integrations/pulse", tags=["integrations.pulse"]
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "5.2.4"}


@sio.on("connect")
async def _sio_connect(sid, environ, auth=None):
    # v3.3.3 — pass the remote address into the auth callback so its rate-limit
    # can kick in (see app.auth.socketio_auth_ok docstring for the LAN-trust
    # rationale). The address is the ASGI scope's peer (behind nginx, the
    # dashboard's real IP via uvicorn --proxy-headers); engineio's ASGI
    # REMOTE_ADDR is a hardcoded placeholder — see socketio_client_addr.
    _log = logging.getLogger(__name__)
    remote_addr = socketio_client_addr(environ)
    if not socketio_auth_ok(auth, remote_addr=remote_addr):
        _log.warning("Socket.IO connect refused: sid=%s remote=%s", sid, remote_addr or "?")
        return False
    track_client_connect(sid, environ)
    _log.info("Socket.IO connect: sid=%s remote=%s", sid, remote_addr or "?")


@sio.on("disconnect")
async def _sio_disconnect(sid):
    track_client_disconnect(sid)


# Outermost layer: the Host allow-list (DNS-rebinding guard, app/host_allow.py)
# wraps Socket.IO as well as every FastAPI route. uvicorn serves this object
# (server/Dockerfile CMD), so nothing reaches the app for an unlisted Host.
# Inside it, the cross-site guard refuses state-changing requests a page on
# another site sent to the Pi's real name.
socket_app = HostAllowMiddleware(CrossSiteRequestGuard(socketio.ASGIApp(sio, app)))
