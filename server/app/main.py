import asyncio
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

    await init_db()
    await seed_builtins()
    await seed_builtin_rules()
    mqtt_task = asyncio.create_task(start_mqtt(sio))
    yield
    mqtt_task.cancel()
    try:
        await mqtt_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="SporePrint", version="0.1.0", lifespan=lifespan)

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

app.include_router(telemetry_router, prefix="/api/telemetry", tags=["telemetry"])
app.include_router(sessions_router, prefix="/api/sessions", tags=["sessions"])
app.include_router(species_router, prefix="/api/species", tags=["species"])
app.include_router(hardware_router, prefix="/api/hardware", tags=["hardware"])
app.include_router(automation_router, prefix="/api/automation", tags=["automation"])
app.include_router(vision_router, prefix="/api/vision", tags=["vision"])
app.include_router(transcript_router, prefix="/api/transcript", tags=["transcript"])
app.include_router(builder_router, prefix="/api/builder", tags=["builder"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


socket_app = socketio.ASGIApp(sio, other_app=app)
