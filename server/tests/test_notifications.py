import json
import time

import httpx
import pytest

import app.notifications.service as notif
from app.notifications.service import (
    _last_sent,
    contamination_alert,
    node_offline,
    notify,
    notify_critical,
    notify_info,
    notify_warning,
)

# Captured before any test patches `httpx.AsyncClient` (the patch replaces the
# attribute on the shared httpx module, so the factory below must not look it up).
_RealAsyncClient = httpx.AsyncClient


@pytest.fixture()
def ntfy(monkeypatch):
    """Route the notifier through a REAL httpx client on a MockTransport.

    Unlike an AsyncMock client, this builds genuine `httpx.Request` objects, so
    header/body encoding errors surface exactly as they would against a live
    ntfy server. Returns the list of captured requests; set `ntfy.status` to
    make the fake server answer with an error.
    """
    class _Recorder(list):
        status = 200

    rec = _Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        rec.append(request)
        return httpx.Response(rec.status, json={"id": "x"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr("app.config.settings.ntfy_url", "http://test:80")
    monkeypatch.setattr("app.config.settings.ntfy_topic", "test")
    monkeypatch.setattr(notif.httpx, "AsyncClient", factory)
    return rec


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


async def test_notify_publishes_json_to_ntfy_root(ntfy):
    await notify("Title", "Message", tags=["mushroom"])
    assert len(ntfy) == 1
    req = ntfy[0]
    assert req.method == "POST"
    # JSON publishing goes to the ntfy ROOT url; the topic travels in the body.
    assert req.url.host == "test"
    assert req.url.path == "/"
    body = _body(req)
    assert body["topic"] == "test"
    assert body["title"] == "Title"
    assert body["message"] == "Message"
    assert body["tags"] == ["mushroom"]


async def test_non_ascii_title_is_delivered(ntfy):
    """httpx encodes header values as ASCII, so an em-dash or °F in
    the old `Title:` header raised UnicodeEncodeError before any connection and
    every contamination / harvest / temperature page was silently dropped."""
    await contamination_alert("Blue Oyster", "trichoderma", 0.9)
    assert len(ntfy) == 1, "contamination alert with an em-dash title was dropped"
    body = _body(ntfy[0])
    assert body["title"] == "CONTAMINATION DETECTED — Blue Oyster"
    assert body["priority"] == 5

    await notify("Temp HIGH: 91.2°F", "hot — check closet")
    assert len(ntfy) == 2
    assert _body(ntfy[1])["title"] == "Temp HIGH: 91.2°F"


async def test_dedup_same_key_within_window(ntfy):
    await notify("Title", "Msg", dedup_key="key1", dedup_seconds=300)
    await notify("Title", "Msg", dedup_key="key1", dedup_seconds=300)
    assert len(ntfy) == 1


async def test_dedup_different_keys_pass(ntfy):
    await notify("Title", "Msg", dedup_key="key1", dedup_seconds=300)
    await notify("Title", "Msg", dedup_key="key2", dedup_seconds=300)
    assert len(ntfy) == 2


async def test_dedup_expired_window_passes(ntfy):
    await notify("Title", "Msg", dedup_key="key1", dedup_seconds=1)
    # Manually expire the entry
    _last_sent["key1"] = time.time() - 10
    await notify("Title", "Msg", dedup_key="key1", dedup_seconds=1)
    assert len(ntfy) == 2


async def test_failed_publish_does_not_consume_dedup_window(ntfy):
    """A POST that fails must not arm the dedup window, otherwise a
    transient ntfy outage suppresses the retry for the whole window."""
    ntfy.status = 503
    await notify("Title", "Msg", dedup_key="k", dedup_seconds=300)
    assert "k" not in _last_sent
    ntfy.status = 200
    await notify("Title", "Msg", dedup_key="k", dedup_seconds=300)
    assert len(ntfy) == 2
    assert "k" in _last_sent


async def test_priority_mapping(ntfy):
    for priority, expected in [("critical", 5), ("warning", 4), ("info", 3), ("default", 3)]:
        _last_sent.clear()
        ntfy.clear()
        await notify("Title", "Msg", priority=priority)
        assert _body(ntfy[0])["priority"] == expected, f"priority={priority}"


async def test_notify_no_url_noop(ntfy, monkeypatch):
    monkeypatch.setattr("app.config.settings.ntfy_url", "")
    await notify("Title", "Msg")
    assert ntfy == []


async def test_critical_repeats_are_deduped(ntfy):
    """The automation engine pages notify_critical on every telemetry
    frame while an emergency persists; identical CRITICAL pages must collapse."""
    for _ in range(5):
        await notify_critical("Temperature EMERGENCY", "temperature 120 (high); threshold 85")
    assert len(ntfy) == 1
    # A different critical still goes out immediately.
    await notify_critical("Humidity EMERGENCY", "humidity 20 (low); threshold 50")
    assert len(ntfy) == 2


async def test_critical_explicit_dedup_key(ntfy):
    await notify_critical("heat in 5h", "m", dedup_key="wx-heat-1-20000")
    await notify_critical("heat in 4h", "m", dedup_key="wx-heat-1-20000")
    assert len(ntfy) == 1


async def test_node_offline_is_critical_tier(ntfy):
    """Node offline belongs to the CRITICAL tier (spec §6)."""
    await node_offline("climate-01")
    assert len(ntfy) == 1
    assert _body(ntfy[0])["priority"] == 5
    await node_offline("climate-01")
    assert len(ntfy) == 1, "repeat offline page for the same node must dedup"


async def test_info_and_warning_dedup_by_title_without_a_key(ntfy):
    """README and feature-status promise INFO at most once an hour and WARNING
    5-min dedup, but notify() dedups only with a key, and the drying-complete
    INFO passed none, so it repeated on every qualifying drying-log entry."""
    await notify_info("Drying Complete — Run 1", "msg")
    await notify_info("Drying Complete — Run 1", "msg")
    await notify_warning("Out of range", "msg")
    await notify_warning("Out of range", "msg")
    assert len(ntfy) == 2
    await notify_info("Drying Complete — Run 2", "msg")
    assert len(ntfy) == 3


def test_module_docstring_describes_the_info_tier_that_exists():
    """INFO is sent at once and deduped per message; there is no hourly batch
    and no daily summary (docs/feature-status.md lists both as not built)."""
    doc = notif.__doc__ or ""
    assert "batched hourly" not in doc and "daily summary" not in doc
    assert "at most once an hour" in doc


# ── pages keyed per source ────────────────────────────────────────────────


async def test_co2_pages_name_their_node_and_never_share_a_key(ntfy):
    await notif.co2_alert(2500, "node-a")
    await notif.co2_alert(45000, "node-b", life_safety=True)
    await notif.co2_alert(2600, "node-a")  # node-a's own repeat collapses
    titles = [_body(r)["title"] for r in ntfy]
    assert titles == ["CO2 CRITICAL on node-a: 2500 ppm", "CO2 CRITICAL on node-b: 45000 ppm"]
    assert "dangerous to people" in _body(ntfy[1])["message"]


def test_a_co2_page_needs_its_node():
    with pytest.raises(TypeError):
        notif.co2_alert(2500)  # no shared, node-less key any more


def test_the_unused_shared_key_temperature_wrapper_is_gone():
    assert not hasattr(notif, "temperature_alert")


async def test_phase_reminders_of_same_named_sessions_both_go_out(ntfy):
    await notif.phase_reminder(1, "Blue Oyster", "fruiting", 40, 7)
    await notif.phase_reminder(2, "Blue Oyster", "fruiting", 40, 7)
    await notif.phase_reminder(1, "Blue Oyster", "fruiting", 41, 7)  # same session
    assert len(ntfy) == 2


async def test_each_page_reuses_one_tls_context(monkeypatch):
    seen = []

    class _Client:
        def __init__(self, *args, verify=None, **kwargs):
            seen.append(verify)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, timeout=None):
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.config.settings.ntfy_url", "https://ntfy.example")
    monkeypatch.setattr(notif.httpx, "AsyncClient", _Client)
    await notify("one", "m")
    await notify("two", "m")
    assert len(seen) == 2 and seen[0] is seen[1] and seen[0] is not None
