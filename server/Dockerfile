# Base image pinned by patch tag AND multi-arch index digest: every build gets
# the same bits on the Pi (arm64) and elsewhere (amd64). Official images stop
# rebuilding a patch tag once it is superseded, so bump tag + digest together
# when a new 3.12.x-slim ships (Debian security fixes land that way too):
#   docker buildx imagetools inspect python:3.12-slim   # "Digest:" line
FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

RUN pip install --no-cache-dir --root-user-action=ignore --upgrade pip && \
    adduser --disabled-password --gecos "" --no-create-home appuser

WORKDIR /app

# Install exactly what uv.lock pins — the set the test suite ran against —
# hash-checked. `--locked` fails the build if pyproject.toml changed without
# re-running `uv lock`. uv is only needed for the export and is removed in the
# same layer.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir --root-user-action=ignore uv==0.12.19 && \
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
# sets X-Forwarded-For. Trust those headers only from Docker's default bridge
# address pool (the compose network) so the server sees each dashboard's real
# address; a LAN client talking to :8000 directly cannot spoof one. Override
# with -e FORWARDED_ALLOW_IPS=<cidr> if your compose network uses another range.
ENV FORWARDED_ALLOW_IPS=172.16.0.0/12

CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
