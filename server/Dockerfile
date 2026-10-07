# Base image pinned by patch tag AND multi-arch index digest: every build gets
# the same bits on the Pi (arm64) and elsewhere (amd64). Official images stop
# rebuilding a patch tag once it is superseded, so bump tag + digest together
# when a new 3.12.x-slim ships (Debian security fixes land that way too):
#   docker buildx imagetools inspect python:3.12-slim   # "Digest:" line
FROM python:3.12.15-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

# Zone files for TZ: compose passes TZ (install.sh writes the host's zone into
# .env) so automation schedules run on the operator's clock, and glibc
# silently falls back to UTC for a zone it cannot find. The Debian trixie base
# ships tzdata (canonical Region/City zones; legacy aliases such as US/Pacific
# live in tzdata-legacy, which install.sh resolves on the host). Install it
# only if a future base drops it, so the usual build stays offline for apt.
RUN pip install --no-cache-dir --root-user-action=ignore --upgrade pip && \
    adduser --disabled-password --gecos "" --no-create-home appuser && \
    if [ ! -f /usr/share/zoneinfo/America/New_York ]; then \
        apt-get update && \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata && \
        rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app

# Install exactly what uv.lock pins — the set the test suite ran against —
# hash-checked. `--locked` fails the build if pyproject.toml changed without
# re-running `uv lock`. uv is only needed for the export and is removed in the
# same layer.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir --root-user-action=ignore uv==0.12.23 && \
    uv export --no-cache --locked --no-dev --no-emit-project --format requirements.txt \
        -o /tmp/requirements.txt && \
    pip install --no-cache-dir --root-user-action=ignore --require-hashes \
        -r /tmp/requirements.txt && \
    pip uninstall -y --root-user-action=ignore uv && \
    rm -f /tmp/requirements.txt

COPY . .

USER appuser

EXPOSE 8000

# The LAN dashboard reaches the API through the ui container's nginx, which
# sets X-Forwarded-For. Trust those headers only from the ui container's fixed
# address on compose's `edge` network, so the server sees each dashboard's
# real address. Not a range: a bridge gateway is where docker-proxy relays
# IPv6/loopback clients of the published :8000 from, and a gateway in the
# trusted range let them forge the header. docker-compose.yml passes the same
# default; move it with FORWARDED_ALLOW_IPS (= SPOREPRINT_EDGE_UI_IP) in .env.
ENV FORWARDED_ALLOW_IPS=172.31.253.2

CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
