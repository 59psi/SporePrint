"""HTTP client for the Aranet PRO local API.

Thin wrapper around `httpx.AsyncClient` so the driver + router can mock
it cleanly in tests. No retry-storm logic at this layer — the poller
handles backoff between polls; a single transient failure should be
visible to the operator (via the driver's `last_error`) so they can
diagnose, not silently absorbed by the client.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import AranetMeasurementsResponse


logger = logging.getLogger(__name__)


class AranetError(RuntimeError):
    """Raised when the PRO returns a non-2xx or unparseable response."""


class AranetClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: float = 5.0):
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._api_key,
            "Accept": "application/json",
            "User-Agent": "sporeprint-pi/aranet-driver",
        }

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(
            timeout=self._timeout_s, follow_redirects=False
        ) as client:
            try:
                resp = await client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                raise AranetError(f"transport error: {exc}") from exc
        if resp.status_code == 401:
            raise AranetError(
                "401 unauthorized — check the X-API-Key value"
            )
        if resp.status_code == 404:
            raise AranetError(
                f"404 from {path} — confirm Aranet PRO firmware ≥ 2.0 (older "
                "firmware does not expose a local API)"
            )
        if resp.status_code >= 400:
            raise AranetError(
                f"HTTP {resp.status_code} from {path}: "
                f"{resp.text[:200]!r}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AranetError(f"non-JSON response: {exc}") from exc

    async def fetch_latest(self) -> AranetMeasurementsResponse:
        """Pull the latest reading per sensor."""
        raw = await self._get("/api/v1/measurements/last")
        return AranetMeasurementsResponse.from_payload(raw)
