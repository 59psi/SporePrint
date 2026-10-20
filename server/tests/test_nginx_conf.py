"""ui/nginx.conf is the LAN dashboard's reverse proxy to the FastAPI server.

It must not be stricter than the server's own per-endpoint upload caps (the
nginx default body limit of 1 MiB rejected every firmware .bin with 413
before FastAPI saw it), and it must tell the server who the real client is.
"""

import re
from pathlib import Path

from app.builder import service as builder_service
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


# A slow but plausible output rate for the Builder guide's model, thinking
# included. The guide reaches nginx only once it is complete, so the proxy
# must wait out a whole generation of up to _GUIDE_MAX_TOKENS.
_SLOW_OUTPUT_TOKENS_PER_SECOND = 40


def test_builder_guide_proxy_outlasts_a_full_length_guide():
    guide = _location(_conf(), "= /api/builder/guide")
    assert re.search(r"proxy_pass\s+http://server:8000\s*;", guide)
    worst_case = builder_service._GUIDE_MAX_TOKENS / _SLOW_OUTPUT_TOKENS_PER_SECOND
    for directive in ("proxy_read_timeout", "proxy_send_timeout"):
        m = re.search(rf"{directive}\s+(\d+)s\s*;", guide)
        assert m and int(m.group(1)) >= worst_case, (directive, worst_case)


def test_both_proxies_forward_the_client_address():
    conf = _conf()
    # A location that sets any proxy_set_header inherits none from /api/, so
    # every proxy location sets the client address itself.
    for prefix in ("/api/", "= /api/builder/guide", "/socket.io/"):
        block = _location(conf, prefix)
        assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr\s*;", block), prefix
        assert re.search(r"proxy_set_header\s+X-Real-IP\s+\$remote_addr\s*;", block), prefix
        assert re.search(r"proxy_set_header\s+Host\s+\$host\s*;", block), prefix
        assert re.search(r"proxy_set_header\s+X-Forwarded-Proto\s+\$scheme\s*;", block), prefix


_NO_FRAMING = (
    re.compile(r"""add_header\s+X-Frame-Options\s+"DENY"\s+always\s*;"""),
    re.compile(r"""add_header\s+Content-Security-Policy\s+"frame-ancestors 'none'"\s+always\s*;"""),
)
_LOCATION_RE = re.compile(r"location\s+([^{]+?)\s*\{([^}]*)\}")


def test_no_other_site_can_frame_the_dashboard():
    """The dashboard switches actuators with no login (LAN-trust), so another
    page must not frame it and click through it (clickjacking). nginx gives a
    location the server-level add_header lines only when it sets none of its
    own, so every location that sets one repeats both."""
    conf = _conf()
    server_level = _LOCATION_RE.sub("", conf)
    for header in _NO_FRAMING:
        assert header.search(server_level), header.pattern
    blocks = {m.group(1): m.group(2) for m in _LOCATION_RE.finditer(conf)}
    assert {"/", "/assets/"} <= set(blocks)
    for prefix, block in blocks.items():
        if "add_header" in block:
            for header in _NO_FRAMING:
                assert header.search(block), (prefix, header.pattern)


def test_index_html_is_revalidated_on_every_load():
    """A heuristically cached index.html kept naming the previous bundle
    after an update; no-cache makes every load revalidate it."""
    root = _location(_conf(), "/")
    assert re.search(r"try_files\s+\$uri\s+\$uri/\s+/index\.html\s*;", root)
    assert re.search(r'add_header\s+Cache-Control\s+"no-cache"\s*;', root)


def test_a_missing_bundle_is_a_404_not_index_html():
    """The SPA fallback answered a request for a replaced chunk with
    index.html (200 text/html), which the browser rejects as a script."""
    assets = _location(_conf(), "/assets/")
    assert re.search(r"try_files\s+\$uri\s+=404\s*;", assets)
    assert "index.html" not in assets
    assert re.search(r'add_header\s+Cache-Control\s+"public, max-age=\d+, immutable"\s*;', assets)


def test_every_bundle_name_carries_its_content_hash():
    # Caching /assets/ as immutable is safe only while every name there
    # changes with its content (Vite's name-<hash>, sync_ui_builder_data.py's
    # index-<sha256[:8]>).
    names = [p.name for p in (NGINX_CONF.parent / "dist" / "assets").iterdir()]
    assert names
    for name in names:
        assert re.fullmatch(r"[\w.-]+-[\w-]{8}\.(js|css|woff2?|map|svg|png)", name), name
