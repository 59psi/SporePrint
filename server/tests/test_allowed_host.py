"""AllowedHostMiddleware — the DNS-rebinding backstop.

The Pi is a LAN appliance that ships with authentication disabled
(`SPOREPRINT_ALLOW_UNAUTHENTICATED=true` from install.sh), so `ApiKeyMiddleware`
short-circuits on a default install and every `/api` route is reachable without
credentials. CORS does not help: `CORSMiddleware` governs what a browser may
READ from a response, not whether the request runs — and a DNS-rebinding page
sidesteps the origin check entirely by re-resolving its own hostname to the Pi's
LAN address, at which point the browser treats the Pi as same-origin.

The Host header is the control that survives that, because page JavaScript
cannot override it. These tests pin that behaviour.
"""

from __future__ import annotations

import pytest


def _get(client, path="/api/health", host=None):
    headers = {"Host": host} if host else {}
    return client.get(path, headers=headers)


class TestRejectsUntrustedHosts:
    @pytest.mark.parametrize(
        "host",
        [
            "evil.example",
            "attacker.com",
            # The rebinding shape: attacker-controlled name, Pi's LAN address.
            "rebind.evil.example:8000",
            # A LAN-looking name embedded in an external domain must not pass.
            "192.168.1.10.evil.example",
            "sporeprint.local.evil.example",
        ],
    )
    def test_untrusted_host_is_rejected(self, client, host):
        res = _get(client, host=host)
        assert res.status_code == 421, (
            f"Host {host!r} was accepted. A web page the owner visits could "
            f"then drive this API, including the pairing → /api/cloud/configure "
            f"chain that hands over the relay-signing credential."
        )
        assert res.json()["error"] == "Untrusted Host header"


class TestAllowsLanHosts:
    @pytest.mark.parametrize(
        "host",
        [
            "localhost",
            "localhost:8000",
            "127.0.0.1",
            "127.0.0.1:8000",
            "sporeprint.local",
            "chambers.local:8000",
            "192.168.1.50",
            "192.168.1.50:8000",
            "10.0.0.7",
            "172.16.4.2",
            "172.31.255.254",
        ],
    )
    def test_lan_host_is_allowed(self, client, host):
        assert _get(client, host=host).status_code == 200

    @pytest.mark.parametrize("host", ["172.15.0.1", "172.32.0.1"])
    def test_addresses_just_outside_rfc1918_are_rejected(self, client, host):
        """172.16/12 spans 172.16–172.31 only; the neighbours are public."""
        assert _get(client, host=host).status_code == 421


class TestConfiguredEscapeHatch:
    def test_named_host_from_settings_is_allowed(self, client, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "trusted_hosts", "pi.example.net")
        assert _get(client, host="pi.example.net").status_code == 200
        # Still rejects anything not named.
        assert _get(client, host="other.example.net").status_code == 421

    def test_wildcard_disables_the_check(self, client, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "trusted_hosts", "*")
        assert _get(client, host="evil.example").status_code == 200


class TestProtectsThePairingChain:
    """The specific chain this middleware exists to break.

    Each step below was reachable unauthenticated from any page the owner
    visited: mint a pairing code, read it back in plaintext, redeem it for a
    configure_token, then rewrite the cloud URL + token.
    """

    @pytest.mark.parametrize(
        "method,path",
        [
            ("post", "/api/cloud/pairing-code"),
            ("get", "/api/cloud/pairing-code"),
            ("post", "/api/cloud/pair"),
            ("post", "/api/cloud/configure"),
        ],
    )
    def test_pairing_chain_is_unreachable_from_a_foreign_host(
        self, client, method, path
    ):
        kwargs = {"headers": {"Host": "evil.example"}}
        if method != "get":
            kwargs["json"] = {}
        res = getattr(client, method)(path, **kwargs)
        assert res.status_code == 421, (
            f"{method.upper()} {path} executed for an attacker-controlled Host."
        )


class TestPublicRoutesAreMethodAware:
    """`_PUBLIC_ROUTES` holds (method, path) pairs, not bare paths.

    Matching on path alone made every method on a listed path public. That
    exempted BOTH `GET /api/cloud/pairing-code` (returns the code in plaintext)
    and `POST /api/cloud/pairing-code` (mints a code and clears the lockout),
    when only redeeming a code was ever meant to be unauthenticated.
    """

    def test_redeeming_a_code_stays_public(self):
        from app.auth import _PUBLIC_ROUTES

        assert ("POST", "/api/cloud/pair") in _PUBLIC_ROUTES

    def test_minting_and_reading_a_code_are_not_public(self):
        from app.auth import _PUBLIC_ROUTES

        for method in ("GET", "POST"):
            assert (method, "/api/cloud/pairing-code") not in _PUBLIC_ROUTES, (
                f"{method} /api/cloud/pairing-code is public. Minting resets the "
                "brute-force lockout and GET discloses the code itself; both are "
                "operator actions and must authenticate."
            )

    def test_no_bare_paths_remain_in_the_set(self):
        """A str entry can never match the (method, path) tuple lookup, so it
        would silently stop exempting whatever it was meant to allow."""
        from app.auth import _PUBLIC_ROUTES

        assert all(isinstance(e, tuple) and len(e) == 2 for e in _PUBLIC_ROUTES)

    def test_camera_upload_and_health_remain_public(self):
        from app.auth import _PUBLIC_ROUTES

        assert ("POST", "/api/vision/frame") in _PUBLIC_ROUTES
        assert ("GET", "/api/health") in _PUBLIC_ROUTES
