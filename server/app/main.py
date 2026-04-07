import asyncio
import logging
import time
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    tasks = [
        asyncio.create_task(start_mqtt(sio)),
        asyncio.create_task(start_weather_polling(sio)),
        asyncio.create_task(start_retention_task()),
        asyncio.create_task(start_cloud_connector()),
        asyncio.create_task(_daily_retrain()),
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


app = FastAPI(title="SporePrint", version="0.2.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from .telemetry.router import router as telemetry_router
from .sessions.router import router as sessions_router
from .species.router import router as species_router
from .hardware.router import router as hardware_router
from .automation.router import router as automation_router
from .vision.router import router as vision_router
from .transcript.router import router as transcript_router
from .builder.router import router as builder_router
from .cloud.router import router as cloud_router
from .health.router import router as health_router
from .weather.router import router as weather_router

app.include_router(telemetry_router, prefix="/api/telemetry", tags=["telemetry"])
app.include_router(sessions_router, prefix="/api/sessions", tags=["sessions"])
app.include_router(species_router, prefix="/api/species", tags=["species"])
app.include_router(hardware_router, prefix="/api/hardware", tags=["hardware"])
app.include_router(automation_router, prefix="/api/automation", tags=["automation"])
app.include_router(vision_router, prefix="/api/vision", tags=["vision"])
app.include_router(transcript_router, prefix="/api/transcript", tags=["transcript"])
app.include_router(builder_router, prefix="/api/builder", tags=["builder"])
app.include_router(weather_router, prefix="/api/weather", tags=["weather"])
app.include_router(cloud_router, prefix="/api/cloud", tags=["cloud"])
app.include_router(health_router, prefix="/api/health/detail", tags=["health"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.2.1"}


# Track Socket.IO clients for health reporting
from .health.service import track_client_connect, track_client_disconnect


@sio.on("connect")
async def _sio_connect(sid, environ):
    track_client_connect(sid, environ)


@sio.on("disconnect")
async def _sio_disconnect(sid):
    track_client_disconnect(sid)


socket_app = socketio.ASGIApp(sio, app)
