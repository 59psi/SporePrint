# sporeprint Pi UI — nginx serving the pre-built dashboard bundle.
#
# The React/Vite source lives in the cloud monorepo at
# frontend/packages/pi-ui/. The build runs there and its `dist/` is
# committed here as `ui/dist/`; this directory holds only that bundle, this
# Dockerfile and nginx.conf. To regenerate the bundle, see README.md →
# Development (`pnpm --filter @sporeprint/pi-ui build`, then
# `rsync -a --delete --checksum frontend/packages/pi-ui/dist/ <this repo>/ui/dist/`).
#
# nginx.conf serves the bundle (index.html revalidated on every load, the
# hashed /assets/ cached for good, no framing by other sites) and proxies
# /api/ + /socket.io/ to the FastAPI server.

# Base pinned to an exact STABLE nginx (even minor; `nginx:alpine` floats with
# mainline) by tag AND multi-arch index digest (amd64, arm64, arm/v7, arm/v6),
# so every `docker compose up --build` on a Pi gets the same proxy. Bump tag
# and digest together; the digest is the Docker-Content-Digest of the tag's
# index, e.g. from `docker buildx imagetools inspect nginx:1.30-alpine`.
# tests/test_docker.py checks the pin.
FROM nginx:1.30.6-alpine@sha256:970364228b1e4f932abc22d321932816782cca8a20b85a77552a7cfe9acfb3b5
COPY dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
