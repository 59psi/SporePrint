"""Cloud-API HTTP client for Pulse Grow.

Holds an in-memory session token. Re-logs in transparently on 401
(token expired). The token is *never* persisted to disk — it lives only
in the running process. The encrypted-at-rest credentials in the
integrations Fernet store are the durable secret; the token is short-
lived working state.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import (
    PulseDeviceListResponse,
    PulseLoginResponse,
    PulseRecentDataResponse,
)


logger = logging.getLogger(__name__)


# Pulse's v2 cloud API base. Configurable for tests; the production
# value is hard-coded here so a typo in operator config cannot point us
# at a malicious origin.
PULSE_API_BASE = "https://api.pulsegrow.com"


class PulseError(RuntimeError):
    """Raised when Pulse returns a non-2xx or unparseable response."""


class PulseCloudClient:
    def __init__(
        self,
        email: str,
        password: str,
        *,
        api_base: str = PULSE_API_BASE,
        timeout_s: float = 10.0,
    ):
        if not email:
            raise ValueError("email is required")
        if not password:
            raise ValueError("password is required")
        self._email = email
        self._password = password
        self._api_base = api_base.rstrip("/")
        self._timeout_s = timeout_s
        self._token: str | None = None

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/json",
            "User-Agent": "sporeprint-pi/pulse-driver",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        url = f"{self._api_base}{path}"
        own_client = client is None
        if own_client:
            client = httpx.AsyncClient(
                timeout=self._timeout_s, follow_redirects=False
            )
        try:
            try:
                resp = await client.request(
                    method, url, headers=self._headers(), json=json
                )
            except httpx.HTTPError as exc:
                raise PulseError(f"transport error: {exc}") from exc
        finally:
            if own_client:
                await client.aclose()

        if resp.status_code == 401 and retry_on_401 and path != "/v2/auth/login":
            # Token expired — discard and try again with a fresh login.
            self._token = None
            await self.login()
            return await self._request(
                method, path, json=json, retry_on_401=False
            )
        if resp.status_code == 401:
            raise PulseError(
                "401 unauthorized — check email + password"
            )
        if resp.status_code == 429:
            raise PulseError("429 rate-limited — back off and retry")
        if resp.status_code >= 400:
            raise PulseError(
                f"HTTP {resp.status_code} from {path}: "
                f"{resp.text[:200]!r}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise PulseError(f"non-JSON response: {exc}") from exc

    async def login(self) -> str:
        """Exchange email + password for a session token."""
        raw = await self._request(
            "POST",
            "/v2/auth/login",
            json={"email": self._email, "password": self._password},
            retry_on_401=False,
        )
        parsed = PulseLoginResponse.from_payload(raw)
        if not parsed.token:
            raise PulseError("login succeeded but no token in response")
        self._token = parsed.token
        return parsed.token

    async def list_devices(self) -> PulseDeviceListResponse:
        if not self._token:
            await self.login()
        raw = await self._request("GET", "/v2/devices")
        return PulseDeviceListResponse.from_payload(raw)

    async def recent_data(self, device_id: str) -> PulseRecentDataResponse:
        if not self._token:
            await self.login()
        raw = await self._request(
            "GET", f"/v2/devices/{device_id}/recent-data?limit=1"
        )
        return PulseRecentDataResponse.from_payload(raw, device_id)

    @property
    def has_token(self) -> bool:
        return self._token is not None
