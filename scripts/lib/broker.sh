# shellcheck shell=bash
#
# scripts/lib/broker.sh — shared helpers for scripts that edit the Mosquitto
# password file. Sourced by scripts/add-node-mqtt-user.sh,
# scripts/rotate-mqtt-creds.sh and setup.sh. (install.sh carries its own copy
# so the `curl … | bash` path never depends on a half-updated checkout; keep
# the two in step.)
#
# Why the ceremony: the broker (eclipse-mosquitto image) drops to its
# unprivileged `mosquitto` user — uid/gid 1883 — right after reading
# mosquitto.conf and BEFORE it opens password_file or the TLS keyfile. A
# 0600 passwd owned by the installing host user (uid 1000) is unreadable to
# it: "Error: Unable to open pwfile", and the broker crash-loops. So on Linux
# hosts the file is handed to 1883:1883 (mode 0600). Once it is, the host
# user can no longer edit it directly, so every edit runs as root inside a
# throwaway container of the SAME image the broker runs (the hash format
# always matches the broker). Docker Desktop (macOS) maps bind-mount
# ownership itself, so no chown there.
#
# Edits are in place (never mosquitto_passwd -c on an existing file):
# per-node users survive, and the inode the running broker's single-file
# bind mount points at stays the same, so a SIGHUP picks the change up.
# Passwords reach mosquitto_passwd on stdin (password + confirmation), never
# as an argument (`-b user pass`): every process, a container's included,
# shows in the host's `ps`.

# Must equal services.mqtt.image in docker-compose.yml (tests/test_docker.py).
SP_MOSQUITTO_IMAGE="eclipse-mosquitto:2.1.2-alpine"
SP_BROKER_UID=1883

SP_DOCKER_MODE=""   # "" (no usable docker) | docker | sudo

# sp_docker_init — find a docker daemon we can talk to: directly, or via sudo
# (the 'docker' group only applies after a re-login). Returns 1 if none.
sp_docker_init() {
  SP_DOCKER_MODE=""
  command -v docker >/dev/null 2>&1 || return 1
  if docker info >/dev/null 2>&1; then
    SP_DOCKER_MODE="docker"
  elif [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1 \
       && sudo docker info >/dev/null 2>&1; then
    SP_DOCKER_MODE="sudo"
  else
    return 1
  fi
}

sp_docker() {
  if [ "$SP_DOCKER_MODE" = "sudo" ]; then sudo docker "$@"; else docker "$@"; fi
}

sp_should_chown() { [ "$(uname -s)" = "Linux" ]; }

# sp_service_account ROOT NAME — print the broker service account NAME is,
# compared in any case, or nothing: server, sp-3p, sp-cmd, sp-telemetry, or
# the Pi server's own login (SPOREPRINT_MQTT_USERNAME in ROOT/.env, else
# ROOT/server/.env). The server drops node frames under these names
# (app/mqtt.py RESERVED_NODE_IDS) and plug frames too, so none can be a node
# or a plug. Needs sp_env_get (scripts/lib/host.sh).
sp_service_account() {
  local root="$1" name account server_user
  name="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')"
  server_user="$(sp_env_get "$root/.env" SPOREPRINT_MQTT_USERNAME)"
  [ -n "$server_user" ] || server_user="$(sp_env_get "$root/server/.env" SPOREPRINT_MQTT_USERNAME)"
  for account in server sp-3p sp-cmd sp-telemetry "$server_user"; do
    if [ -n "$account" ] && [ "$name" = "$(printf '%s' "$account" | tr '[:upper:]' '[:lower:]')" ]; then
      printf '%s' "$account"
      return 0
    fi
  done
}

# sp_passwd_update ROOT — set/replace users in ROOT/config/mosquitto/passwd.
# Reads alternating "user" / "password" lines on stdin (never argv, so the
# secrets stay out of the host's `ps`). Creates the file if missing; keeps
# every other entry. Requires sp_docker_init to have succeeded.
sp_passwd_update() {
  local root="$1" chown_flag=0
  sp_should_chown && chown_flag=1
  # shellcheck disable=SC2016  # the -c script expands inside the container
  sp_docker run --rm -i -e SP_CHOWN="$chown_flag" -e SP_UID="$SP_BROKER_UID" \
    -v "$root/config/mosquitto:/work" --entrypoint sh "$SP_MOSQUITTO_IMAGE" -c '
      set -e
      [ -f /work/passwd ] || : > /work/passwd
      while IFS= read -r u && IFS= read -r p; do
        [ -n "$u" ] || continue
        printf "%s\n%s\n" "$p" "$p" | mosquitto_passwd /work/passwd "$u" >/dev/null
      done
      if [ "$SP_CHOWN" = "1" ]; then chown "$SP_UID:$SP_UID" /work/passwd; fi
      chmod 600 /work/passwd'
}

# sp_host_passwd_set FILE USER PASSWORD — set one user with the HOST's
# mosquitto_passwd, for a host without docker. A shell function, so the
# password is in no process's argv; mosquitto_passwd reads it on stdin.
# Creates FILE if missing (mode 0600); keeps every other entry.
sp_host_passwd_set() {
  local file="$1" user="$2" pass="$3"
  [ -f "$file" ] || : > "$file"
  printf '%s\n%s\n' "$pass" "$pass" | mosquitto_passwd "$file" "$user" >/dev/null
  chmod 600 "$file"
}

# sp_broker_own ROOT RELPATH... — hand files under ROOT/config/mosquitto to
# the broker uid (Linux only; no-op elsewhere). Requires sp_docker_init.
sp_broker_own() {
  local root="$1"; shift
  sp_should_chown || return 0
  local p targets=()
  for p in "$@"; do targets+=("/work/$p"); done
  sp_docker run --rm -v "$root/config/mosquitto:/work" --entrypoint chown \
    "$SP_MOSQUITTO_IMAGE" "$SP_BROKER_UID:$SP_BROKER_UID" "${targets[@]}"
}

# sp_broker_running ROOT — true if the compose `mqtt` service is up.
sp_broker_running() {
  local root="$1"
  [ -n "$SP_DOCKER_MODE" ] || return 1
  [ -n "$(sp_docker compose -f "$root/docker-compose.yml" ps -q --status running mqtt 2>/dev/null)" ]
}

# sp_broker_reload ROOT — SIGHUP the compose broker so it re-reads passwd +
# acl.conf. Prints the manual command when it cannot.
sp_broker_reload() {
  local root="$1" prefix=""
  [ "$SP_DOCKER_MODE" = "sudo" ] && prefix="sudo "
  if sp_broker_running "$root" \
     && sp_docker compose -f "$root/docker-compose.yml" kill -s HUP mqtt >/dev/null 2>&1; then
    echo "✓ broker reloaded (SIGHUP → re-read passwd + ACL)"
  else
    echo "⚠ The broker is not running here (or could not be signalled). It picks the"
    echo "  change up when it starts; if it is already running, reload it with:"
    echo "    cd $root && ${prefix}docker compose kill -s HUP mqtt"
  fi
}
