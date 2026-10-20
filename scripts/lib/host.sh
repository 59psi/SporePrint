# shellcheck shell=bash
#
# scripts/lib/host.sh — host facts and .env helpers shared by setup.sh.
# (install.sh carries its own copies — env_get(), env_set(), host_timezone(),
# server_san() — so the `curl … | bash` path never depends on a half-updated
# checkout; keep the two in step. server/tests/test_provision_scripts.py runs
# both against the same fake host and compares.)

# sp_env_get FILE KEY — KEY's value in FILE as docker compose reads it, or
# nothing: the last line wins; surrounding quotes are removed (a double-quoted
# value also unescapes \" \\ \$ \n \t \r); an unquoted value loses its outer
# blanks and a trailing " # comment"; an `export ` prefix is allowed. A value
# read verbatim ("pw" with its quotes) would not be the one compose hands the
# server.
sp_env_get() {
  [ -f "$1" ] || return 0
  SP_ENV_KEY="$2" awk '
    BEGIN { k = ENVIRON["SP_ENV_KEY"] }
    {
      line = $0
      sub(/\r$/, "", line)
      sub(/^[ \t]*export[ \t]+/, "", line)
      if (index(line, k "=") != 1) next
      v = substr(line, length(k) + 2)
      sub(/^[ \t]+/, "", v)
      q = substr(v, 1, 1)
      if (q == "\"" || q == "\047") {
        out = ""
        for (i = 2; i <= length(v); i++) {
          c = substr(v, i, 1)
          if (c == q) break
          if (q == "\"" && c == "\\" && i < length(v)) {
            i++; c = substr(v, i, 1)
            if (c == "n") c = "\n"
            else if (c == "t") c = "\t"
            else if (c == "r") c = "\r"
            else if (c != "\\" && c != "\"" && c != "$") c = "\\" c
          }
          out = out c
        }
        v = out
      } else {
        sub(/[ \t]+#.*$/, "", v)
        sub(/[ \t]+$/, "", v)
      }
      last = v; found = 1
    }
    END { if (found) printf "%s", last }' "$1"
}

# sp_env_set FILE KEY VALUE — replace KEY in place, or append it. Mode 0600.
# The value reaches awk in its environment, never on its command line (the
# host's process table) or through -v (which rewrites backslash escapes).
# awk ends every line it writes with a newline, so a last line saved without
# one never has the new key glued onto it.
sp_env_set() {
  local file="$1" src="$1" tmp
  [ -f "$file" ] || src=/dev/null
  tmp="$(mktemp)"
  SP_ENV_KEY="$2" SP_ENV_VAL="$3" awk '
    BEGIN { FS = OFS = "="; k = ENVIRON["SP_ENV_KEY"]; v = ENVIRON["SP_ENV_VAL"] }
    $1 == k { print k "=" v; seen = 1; next }
    { print }
    END { if (!seen) print k "=" v }' "$src" > "$tmp"
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

# sp_issue_server_cert CERT_DIR HOST_NAME [IP...] — (re)issue server.key +
# server.crt from the CA in CERT_DIR (ca.crt + ca.key). Both are made in a
# directory inside CERT_DIR (the same filesystem, so each rename is atomic)
# and moved into place only once both exist; on any failure the old pair
# stays and this returns 1. Identical to install.sh's issue_server_cert().
sp_issue_server_cert() {
  local dir="$1" host="$2" tmp
  shift 2
  tmp="$(mktemp -d "$dir/.issue.XXXXXX")" || return 1
  if openssl req -newkey rsa:2048 -nodes \
       -keyout "$tmp/server.key" -out "$tmp/server.csr" \
       -subj "/CN=sporeprint.local" 2>/dev/null \
     && openssl x509 -req -in "$tmp/server.csr" \
       -CA "$dir/ca.crt" -CAkey "$dir/ca.key" \
       -CAcreateserial -CAserial "$tmp/ca.srl" \
       -days 1825 -out "$tmp/server.crt" \
       -extfile <(printf 'subjectAltName=%s' "$(sp_server_san "$host" "$@")") 2>/dev/null \
     && chmod 600 "$tmp/server.key" && chmod 644 "$tmp/server.crt" \
     && mv -f "$tmp/server.key" "$dir/server.key" \
     && mv -f "$tmp/server.crt" "$dir/server.crt"; then
    rm -rf "$tmp"
    return 0
  fi
  rm -rf "$tmp"
  return 1
}

# sp_cert_reissue_reason CERT_DIR [IP] — why CERT_DIR/server.crt must be
# re-issued from the CA (it expires within 30 days, or does not name IP), or
# nothing. Identical to install.sh's cert_reissue_reason().
sp_cert_reissue_reason() {
  local crt="$1/server.crt" ip="${2:-}"
  if ! openssl x509 -in "$crt" -noout -checkend $((30 * 86400)) >/dev/null 2>&1; then
    printf 'it expires within 30 days'
  elif [ -n "$ip" ] && ! openssl x509 -in "$crt" -noout -text 2>/dev/null \
       | grep -E "IP Address:$(printf '%s' "$ip" | sed 's/\./\\./g')(,|\$)" >/dev/null; then
    # (grep reads to the end: an early -q exit could SIGPIPE openssl, and
    # under pipefail that would read as "not covered".)
    printf 'it does not cover %s' "$ip"
  fi
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
