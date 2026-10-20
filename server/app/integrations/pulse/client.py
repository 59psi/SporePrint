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
from pydantic import ValidationError

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


class PulseLoginRefused(PulseError):
    """Pulse refused the account's email + password (401 on login)."""


_LOGIN_PATH = "/v2/auth/login"


def _parse(from_payload, raw, *args):
    """Run a model's from_payload on a response body; a body that still does
    not validate is a PulseError like any other bad response, not a crash."""
    try:
        return from_payload(raw, *args)
    except ValidationError as exc:
        raise PulseError(f"unexpected response shape: {exc}") from exc


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
        # Pulse's answer to a login it refused. These credentials are not
        # sent again (repeated failed logins can lock the account) until
        # clear_login_refusal(): the driver calls it on every save, and a
        # credential change builds a new client.
        self._login_refused: str | None = None

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

        if resp.status_code == 401 and retry_on_401 and path != _LOGIN_PATH:
            # Token expired — discard and try again with a fresh login.
            self._token = None
            await self.login()
            return await self._request(
                method, path, json=json, retry_on_401=False
            )
        if resp.status_code == 401:
            error = PulseLoginRefused if path == _LOGIN_PATH else PulseError
            raise error("401 unauthorized — check email + password")
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
        """Exchange email + password for a session token.

        A login Pulse refuses (401, or a reply without a token) is
        remembered: this client then fails at once instead of sending the
        same credentials every poll. Network errors are not remembered.
        """
        if self._login_refused is not None:
            raise PulseError(self._login_refused)
        try:
            raw = await self._request(
                "POST",
                _LOGIN_PATH,
                json={"email": self._email, "password": self._password},
                retry_on_401=False,
            )
        except PulseLoginRefused as exc:
            self._login_refused = (
                f"{exc} (not retried until the credentials are saved again)"
            )
            raise PulseError(self._login_refused) from exc
        parsed = _parse(PulseLoginResponse.from_payload, raw)
        if not parsed.token:
            self._login_refused = (
                "login succeeded but no token in response "
                "(not retried until the credentials are saved again)"
            )
            raise PulseError(self._login_refused)
        self._token = parsed.token
        return parsed.token

    def clear_login_refusal(self) -> None:
        """Allow one more login with these credentials (an operator save)."""
        self._login_refused = None

    async def list_devices(self) -> PulseDeviceListResponse:
        if not self._token:
            await self.login()
        raw = await self._request("GET", "/v2/devices")
        return _parse(PulseDeviceListResponse.from_payload, raw)

    async def recent_data(self, device_id: str) -> PulseRecentDataResponse:
        if not self._token:
            await self.login()
        raw = await self._request(
            "GET", f"/v2/devices/{device_id}/recent-data?limit=1"
        )
        return _parse(PulseRecentDataResponse.from_payload, raw, device_id)

    @property
    def has_token(self) -> bool:
        return self._token is not None
