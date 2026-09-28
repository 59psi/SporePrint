# sporeprint Pi UI — nginx serving the v4 pre-built bundle.
#
# v4: the React/Vite source for the Pi UI lives in the cloud monorepo
# at frontend/packages/pi-ui/. The build runs there
# (`pnpm --filter @sporeprint/pi-ui build`) and the resulting `dist/`
# is committed into this submodule's `dist/` for distribution. The
# submodule's `src/`, `package.json`, etc. are kept around for git
# history but no longer drive the build — they're v3.4-era reference
# material.
#
# To regenerate the dist:
#   1. cd ../..    (back to the cloud monorepo)
#   2. pnpm --filter @sporeprint/pi-ui build
#   3. rsync -a --delete frontend/packages/pi-ui/dist/ sporeprint/ui/dist/
#   4. Commit the resulting sporeprint/ui/dist/ change as a submodule PR.
#
# The Pi nginx config (nginx.conf) is unchanged — same try_files SPA
# fallback, same /api/ + /socket.io/ proxy to the FastAPI server.

# Base pinned to an exact STABLE nginx (even minor; `nginx:alpine` floats with
# mainline) by tag AND multi-arch index digest (amd64, arm64, arm/v7, arm/v6),
# so every `docker compose up --build` on a Pi gets the same proxy. Bump tag
# and digest together; the digest is the Docker-Content-Digest of the tag's
# index, e.g. from `docker buildx imagetools inspect nginx:1.30-alpine`.
# tests/test_docker.py checks the pin.
FROM nginx:1.30.5-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94
COPY dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
