"""$SYS broker-stats feed → health/service._mqtt_stats.

update_mqtt_stat existed since the health dashboard shipped but nothing
ever called it — GET /api/health/detail/mqtt always returned {}. The fix
subscribes to a curated $SYS/broker/* set and routes payloads (plain
text, not JSON) around the JSON-parse in the message loop.
"""

from app import mqtt as mqtt_mod
from app.health import service as health_service


def _reset_stats():
    health_service._mqtt_stats.clear()


def test_sys_message_stored_with_prefix_stripped():
    _reset_stats()
    mqtt_mod._handle_sys_message("$SYS/broker/clients/connected", b"4")
    assert health_service.get_mqtt_stats() == {"clients/connected": "4"}


def test_sys_message_strips_whitespace():
    _reset_stats()
    mqtt_mod._handle_sys_message("$SYS/broker/version", b"mosquitto version 2.0.18\n")
    assert health_service.get_mqtt_stats()["version"] == "mosquitto version 2.0.18"


def test_sys_message_undecodable_payload_is_swallowed():
    _reset_stats()
    # Invalid UTF-8 must not raise out of the message loop.
    mqtt_mod._handle_sys_message("$SYS/broker/uptime", b"\xff\xfe")
    assert health_service.get_mqtt_stats() == {}


def test_curated_topic_list_is_broker_scoped():
    # Every subscription is under $SYS/broker/ — the handler's prefix
    # stripping relies on it.
    assert mqtt_mod._SYS_TOPICS
    for topic in mqtt_mod._SYS_TOPICS:
        assert topic.startswith("$SYS/broker/")
