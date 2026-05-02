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

FROM nginx:alpine
COPY dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
