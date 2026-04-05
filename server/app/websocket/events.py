import logging

log = logging.getLogger(__name__)


def register_events(sio):
    @sio.event
    async def connect(sid, environ):
        log.info("Client connected: %s", sid)

    @sio.event
    async def disconnect(sid):
        log.info("Client disconnected: %s", sid)

    @sio.event
    async def subscribe_telemetry(sid, data=None):
        await sio.enter_room(sid, "telemetry")
        log.info("Client %s subscribed to telemetry", sid)


async def broadcast_telemetry(sio, node_id: str, data: dict):
    await sio.emit("telemetry", {"node_id": node_id, **data}, room="telemetry")
