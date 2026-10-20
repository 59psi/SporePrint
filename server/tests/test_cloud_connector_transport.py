"""The cloud connector can actually open its socket.

python-socketio's asyncio client (app.cloud.service's AsyncClient) needs
aiohttp for its HTTP/WebSocket transport. Without it, every connect fails with
"aiohttp package not installed" and the Pi never reaches the cloud: no
telemetry, no commands, no session sync. Nothing in the locked dependencies
pulled it in, so the Docker image and a fresh install shipped a connector that
could not connect.
"""
import tomllib
from pathlib import Path

import socketio

SERVER = Path(__file__).resolve().parents[1]


def test_the_asyncio_client_transport_is_a_declared_dependency():
    deps = tomllib.loads((SERVER / "pyproject.toml").read_text())["project"]["dependencies"]
    socketio_dep = next(d for d in deps if d.startswith("python-socketio"))
    assert "[asyncio_client]" in socketio_dep, socketio_dep
    lock = (SERVER / "uv.lock").read_text()
    assert 'name = "aiohttp"' in lock


def test_aiohttp_is_importable_where_the_connector_runs():
    import aiohttp  # noqa: F401 — the engineio asyncio client imports it at connect


def test_the_connector_client_can_build_its_transport():
    from engineio import async_client

    client = socketio.AsyncClient(reconnection=False)
    assert async_client.aiohttp is not None
    assert client.eio is not None
