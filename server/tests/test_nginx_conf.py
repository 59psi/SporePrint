"""ui/nginx.conf is the LAN dashboard's reverse proxy to the FastAPI server.

It must not be stricter than the server's own per-endpoint upload caps (the
nginx default body limit of 1 MiB rejected every firmware .bin with 413
before FastAPI saw it), and it must tell the server who the real client is.
"""

import re
from pathlib import Path

from app.contamination import router as contamination_router
from app.hardware import ota_push
from app.vision import router as vision_router

NGINX_CONF = Path(__file__).resolve().parents[2] / "ui" / "nginx.conf"

_SIZE_UNITS = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def _conf() -> str:
    # Drop comments so documentation can't satisfy a directive check.
    return re.sub(r"#[^\n]*", "", NGINX_CONF.read_text())


def _location(conf: str, prefix: str) -> str:
    m = re.search(r"location\s+" + re.escape(prefix) + r"\s*\{([^}]*)\}", conf)
    assert m, f"location {prefix} missing from nginx.conf"
    return m.group(1)


def _body_limit_bytes(conf: str) -> int:
    m = re.search(r"client_max_body_size\s+(\d+)([kKmMgG]?)\s*;", conf)
    assert m, "client_max_body_size not set — nginx defaults to 1m"
    return int(m.group(1)) * _SIZE_UNITS[m.group(2).lower()]


def test_body_limit_admits_every_server_upload_cap():
    limit = _body_limit_bytes(_conf())
    largest_cap = max(
        ota_push.MAX_UPLOAD_BYTES,               # node firmware .bin push
        contamination_router._MAX_IMAGE_SIZE,    # contamination photo identify
        vision_router._MAX_UPLOAD_BYTES,         # vision frame upload
    )
    # Strictly above: multipart framing rides on top of the file itself, and
    # FastAPI's own 413 carries the useful per-endpoint message.
    assert limit > largest_cap


def test_real_firmware_image_fits():
    # Built v5 images are 1.05–1.15 MB, all over the 1 MiB nginx default.
    assert _body_limit_bytes(_conf()) > 1_146_224


def test_api_proxy_allows_slow_claude_calls():
    api = _location(_conf(), "/api/")
    m = re.search(r"proxy_read_timeout\s+(\d+)s\s*;", api)
    assert m and int(m.group(1)) > 60


def test_both_proxies_forward_the_client_address():
    conf = _conf()
    for prefix in ("/api/", "/socket.io/"):
        block = _location(conf, prefix)
        assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr\s*;", block), prefix
        assert re.search(r"proxy_set_header\s+X-Real-IP\s+\$remote_addr\s*;", block), prefix
