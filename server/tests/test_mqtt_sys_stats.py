"""$SYS broker-stats feed → health/service._mqtt_stats.

update_mqtt_stat existed since the health dashboard shipped but nothing
ever called it — GET /api/health/detail/mqtt always returned {}. The loop
subscribes to a curated $SYS/broker/* set and routes those payloads (plain
text, not JSON) around the JSON decode that would drop them.
"""

import app.mqtt
from app.health import service as health_service
from tests._pi_b1_mqtt import FakeBroker, Message, node_row, run_mqtt_loop


async def test_broker_stats_reach_the_mqtt_health_detail(monkeypatch):
    monkeypatch.setattr(health_service, "_mqtt_stats", {})
    broker = FakeBroker([
        Message("$SYS/broker/clients/connected", b"4"),
        Message("$SYS/broker/version", b"mosquitto version 2.0.18\n"),
        # Not UTF-8: swallowed, and the loop carries on.
        Message("$SYS/broker/uptime", b"\xff\xfe"),
        Message("sporeprint/node-s1/status", b'{"status": "online"}'),
    ])
    await run_mqtt_loop(monkeypatch, broker)

    assert set(app.mqtt._SYS_TOPICS) <= set(broker.subscriptions)
    # Every subscription is under $SYS/broker/, which the handler strips.
    assert all(t.startswith("$SYS/broker/") for t in app.mqtt._SYS_TOPICS)
    assert health_service.get_mqtt_stats() == {
        "clients/connected": "4", "version": "mosquitto version 2.0.18"}
    assert (await node_row("node-s1"))["status"] == "online"
