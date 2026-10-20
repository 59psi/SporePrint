"""The timestamp contract for anything a node stamps (telemetry `ts`, a
camera frame's X-Timestamp).

A node's clock is Unix-epoch seconds once it is NTP-synced; before that it is
the node's uptime, which is always below SYNCED_TS_MIN (2001-09-09), and the
Pi stamps the arrival time instead. A synced clock more than
MAX_FUTURE_SKEW_SECONDS ahead of the Pi (a bogus sync) is no capture time
either: stored as is, the reading would sort as the newest one until real
time caught up with it, so it too is stamped with its arrival time.

A leaf module (no app imports), shared by mqtt.py and vision/service.py.
"""

SYNCED_TS_MIN = 1_000_000_000
MAX_FUTURE_SKEW_SECONDS = 300
