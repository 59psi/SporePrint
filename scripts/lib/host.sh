# shellcheck shell=bash
#
# scripts/lib/host.sh — host facts and .env helpers shared by setup.sh.
# (install.sh carries its own copies — host_timezone(), server_san() — so the
# `curl … | bash` path never depends on a half-updated checkout; keep the two
# in step. server/tests/test_provision_scripts.py runs both against the same
# fake host and compares.)

# sp_env_get FILE KEY — print KEY's value from FILE (last one wins), or nothing.
sp_env_get() {
  [ -f "$1" ] || return 0
  grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

# sp_env_set FILE KEY VALUE — replace KEY in place, or append it. Mode 0600.
sp_env_set() {
  local file="$1" key="$2" val="$3" tmp
  tmp="$(mktemp)"
  if [ -f "$file" ] && grep -qE "^${key}=" "$file"; then
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' "$file" > "$tmp"
  else
    { [ -f "$file" ] && cat "$file"; printf '%s=%s\n' "$key" "$val"; } > "$tmp"
  fi
  mv "$tmp" "$file"
  chmod 600 "$file"
}

# sp_host_ipv4s — this host's non-loopback IPv4 addresses, one per line.
# Linux: `hostname -I`. macOS / BSD (no -I): parse `ifconfig`.
sp_host_ipv4s() {
  local ips
  ips="$(hostname -I 2>/dev/null || true)"
  if [ -z "$ips" ] && command -v ifconfig >/dev/null 2>&1; then
    ips="$(ifconfig 2>/dev/null | awk '$1 == "inet" {sub(/^addr:/, "", $2); print $2}' || true)"
  fi
  printf '%s\n' "$ips" | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | grep -v '^127\.' || true
}

# sp_server_san HOST_NAME [IP...] — the broker certificate's subjectAltName.
# Each IPv4 is listed twice: IP:<ip> for standard clients (mosquitto_sub,
# Python) and DNS:<ip> because arduino-esp32 2.x (mbedTLS 2.28) compares the
# host string against SAN entries verbatim and cannot match an iPAddress
# entry. Identical to install.sh's server_san().
sp_server_san() {
  local host="$1" san ip
  shift
  san="DNS:sporeprint.local,DNS:${host}.local,DNS:${host},DNS:localhost,IP:127.0.0.1"
  for ip in "$@"; do san="${san},IP:${ip},DNS:${ip}"; done
  printf '%s' "$san"
}

# sp_host_timezone — the host's IANA zone (e.g. America/Los_Angeles), or
# nothing when it cannot be determined. The server's automation schedules
# (photoperiod, time windows, cron) run on the container's local time, which
# is UTC unless compose passes TZ. Sources, in order: timedatectl (systemd),
# /etc/timezone (Debian), the /etc/localtime symlink (macOS, most Linux).
# A legacy alias (US/Pacific) is resolved to its canonical zone when the host
# ships it as a symlink: the server image carries canonical Region/City zones
# only, and glibc silently falls back to UTC for a zone it cannot find.
sp_host_timezone() {
  local zi="${SP_ZONEINFO_DIR:-/usr/share/zoneinfo}" tz="" real=""
  if command -v timedatectl >/dev/null 2>&1; then
    tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  fi
  if [ -z "$tz" ] && [ -r /etc/timezone ]; then
    tz="$(head -n 1 /etc/timezone 2>/dev/null | tr -d '[:space:]' || true)"
  fi
  if [ -z "$tz" ] && [ -L /etc/localtime ]; then
    tz="$(readlink /etc/localtime 2>/dev/null || true)"
    tz="${tz##*zoneinfo/}"
  fi
  if [ -n "$tz" ] && [ -L "$zi/$tz" ]; then
    real="$(readlink -f "$zi/$tz" 2>/dev/null || true)"
    case "$real" in */zoneinfo/*) tz="${real##*/zoneinfo/}" ;; esac
  fi
  tz="${tz#posix/}"
  printf '%s\n' "$tz" | grep -Eq '^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$' || return 0
  if [ -d "$zi" ] && [ ! -f "$zi/$tz" ]; then return 0; fi
  printf '%s' "$tz"
}

# sp_ensure_signing_key ROOT — make sure ROOT/.env holds the cmd/* signing
# key (SPOREPRINT_MQTT_HMAC_KEY) and print it. Reuses a key already in
# ROOT/.env, then one an older scripts/provision-node.sh left in
# ROOT/server/.env (nodes may already hold it), else generates one. With a
# key set the Pi signs every command: nodes with no key accept signed frames,
# keyed nodes verify them — and a cloud-paired Pi (signing enforced) never
# drops commands for want of a key.
sp_ensure_signing_key() {
  local root="$1" key
  key="$(sp_env_get "$root/.env" SPOREPRINT_MQTT_HMAC_KEY)"
  [ -n "$key" ] && { printf '%s' "$key"; return 0; }
  key="$(sp_env_get "$root/server/.env" SPOREPRINT_MQTT_HMAC_KEY)"
  [ -n "$key" ] || key="$(openssl rand -hex 32)"
  sp_env_set "$root/.env" SPOREPRINT_MQTT_HMAC_KEY "$key"
  printf '%s' "$key"
}
