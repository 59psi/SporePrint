"""Local-mode transport for Pulse Grow devices.

Two phases:

1. **UDP discovery.** A short broadcast on
   ``<local_broadcast_addr>:<local_discovery_port>`` (default
   255.255.255.255:5683) elicits a response from each Pulse device on
   the LAN with its IP and a device-id token. Limited broadcast can be
   blocked by some routers — operators set ``local_broadcast_addr`` to
   the subnet broadcast (e.g. ``10.0.0.255``) if so. Operators can
   bypass discovery entirely by setting ``local_device_urls``.

2. **HTTP polling.** For each discovered (or configured) device, GET
   ``http://<device-ip>:<port>/api/recent-data`` returns a measurement
   payload that this module normalises into the same
   ``PulseRecentDataResponse`` shape used by the cloud transport.

⚠ **Live-device verification needed.** The CoAP-style discovery shape
and the local HTTP path were inferred from secondary sources; the
parsing layer is tolerant by design (unknown payload shapes degrade to
empty rather than crashing the poll), but operators with paired Pulse
hardware should report any device-side payload differences so the
parser gets refined. The driver flag ``test_connection`` exists exactly
for that workflow.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass

import httpx

from .client import PulseError
from .config import PulseConfig
from .models import PulseDeviceListResponse, PulseRecentDataResponse


logger = logging.getLogger(__name__)


_DISCOVERY_PROBE = b"sporeprint-pulse-discover"


@dataclass
class DiscoveredPulseDevice:
    device_id: str
    base_url: str


async def _udp_broadcast_scan(
    broadcast_addr: str,
    port: int,
    timeout_s: float,
    *,
    sock_factory=None,
) -> list[DiscoveredPulseDevice]:
    """Send a UDP broadcast probe; collect responders for `timeout_s`.

    `sock_factory` is for tests. Production passes None and the function
    creates a real datagram socket.
    """
    devices: list[DiscoveredPulseDevice] = []

    def _make_socket() -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setblocking(False)
        return s

    sock = (sock_factory or _make_socket)()
    try:
        loop = asyncio.get_event_loop()
        await loop.sock_sendto(sock, _DISCOVERY_PROBE, (broadcast_addr, port))
        try:
            async with asyncio.timeout(timeout_s):
                while True:
                    data, addr = await loop.sock_recvfrom(sock, 4096)
                    parsed = _parse_discovery_response(data, addr[0])
                    if parsed is not None:
                        devices.append(parsed)
        except TimeoutError:
            pass  # End-of-window; this is expected.
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("pulse local: discovery recv failed")
    finally:
        sock.close()

    return devices


def _parse_discovery_response(
    payload: bytes, source_ip: str
) -> DiscoveredPulseDevice | None:
    """Best-effort parser for a Pulse discovery response.

    Defensive — accepts plain JSON, CoAP-style payloads with a JSON
    body, or just an empty response (in which case we use the source IP
    as the device id since at least we know there's *something* there).
    """
    try:
        text = payload.decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        text = ""

    device_id: str | None = None
    if text.startswith("{"):
        # Plain JSON body or CoAP frame whose payload starts with JSON.
        try:
            import json
            obj = json.loads(text)
            if isinstance(obj, dict):
                device_id = obj.get("device_id") or obj.get("id") or obj.get("serial")
        except Exception:  # noqa: BLE001
            device_id = None

    if device_id is None:
        # Fall back to the source IP. Less informative but still
        # gives the operator something to map to a chamber.
        device_id = f"local:{source_ip}"

    return DiscoveredPulseDevice(
        device_id=device_id, base_url=f"http://{source_ip}"
    )


async def discover_devices(
    cfg: PulseConfig,
    *,
    sock_factory=None,
) -> list[DiscoveredPulseDevice]:
    if cfg.local_device_urls:
        return [
            DiscoveredPulseDevice(
                device_id=f"local:{url}", base_url=url.rstrip("/")
            )
            for url in cfg.local_device_urls
        ]
    return await _udp_broadcast_scan(
        cfg.local_broadcast_addr,
        cfg.local_discovery_port,
        cfg.local_discovery_timeout_seconds,
        sock_factory=sock_factory,
    )


class PulseLocalTransport:
    """LAN-only client. Mirrors the surface of `PulseCloudClient` so the
    poller can swap transports without caring which is in use.
    """

    def __init__(self, cfg: PulseConfig, *, http_client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._http_client = http_client
        self._devices: list[DiscoveredPulseDevice] = []

    async def _ensure_devices(self) -> list[DiscoveredPulseDevice]:
        if not self._devices:
            self._devices = await discover_devices(self._cfg)
        return self._devices

    async def list_devices(self) -> PulseDeviceListResponse:
        devices = await self._ensure_devices()
        return PulseDeviceListResponse(
            devices=[
                {"id": d.device_id, "name": d.device_id, "type": "pulse_local"}
                for d in devices
            ]
        )

    async def recent_data(self, device_id: str) -> PulseRecentDataResponse:
        target = next(
            (d for d in await self._ensure_devices() if d.device_id == device_id),
            None,
        )
        if target is None:
            raise PulseError(f"local device {device_id!r} not in discovered set")
        url = f"{target.base_url}:{self._cfg.local_http_port}/api/recent-data"
        client = self._http_client or httpx.AsyncClient(
            timeout=self._cfg.request_timeout_seconds, follow_redirects=False
        )
        own_client = self._http_client is None
        try:
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                raise PulseError(f"local transport error: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()
        if resp.status_code >= 400:
            raise PulseError(
                f"HTTP {resp.status_code} from local device: {resp.text[:200]!r}"
            )
        try:
            raw = resp.json()
        except ValueError as exc:
            raise PulseError(f"non-JSON response from local device: {exc}") from exc
        return PulseRecentDataResponse.from_payload(raw, device_id)

    async def login(self) -> str:
        # Local transport doesn't have a session — provide a no-op so
        # the poller's "ensure logged in" pattern is uniform.
        return "local"

    @property
    def has_token(self) -> bool:
        return True
