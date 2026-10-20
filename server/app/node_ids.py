"""Node id and channel name syntax.

One definition for every surface that puts a node id or a channel name into
an MQTT topic, a file path or a trust decision: the LAN hardware routes, the
cloud command gate, the camera upload gate and the frame store. The firmware
caps node ids at 32 characters (``sp_core`` provisioning) and channel names
are the short bank names, so both share the pattern.

A leaf module (no app imports), so ``cloud/service.py``, which ``mqtt.py``
imports at module top, can use it without an import cycle. ``\\Z`` rather than
``$``: ``$`` also matches before a trailing newline, which would let
``"node\\n"`` through a ``match()`` into a topic.
"""

import re

NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}\Z")
CHANNEL_RE = NODE_ID_RE


def is_safe_id(value) -> bool:
    """True when ``value`` is a string node id or channel name of that syntax."""
    return isinstance(value, str) and NODE_ID_RE.match(value) is not None
