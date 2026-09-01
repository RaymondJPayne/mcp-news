#!/bin/sh
# Make the mounted directories writable, then drop root before doing anything else.
#
# On Docker Desktop for Windows and macOS a bind mount is writable by any uid, so
# this is a no-op. On Linux the mounted directories belong to the host user and a
# container running as an unprivileged uid cannot write its own configuration —
# which would break the setup wizard for exactly the person this project is for.
#
# The application itself never runs as root: this script is the only thing that
# does, and it hands over with exec.
set -e

APP_USER=mcpnews

if [ "$(id -u)" = "0" ]; then
    for dir in "${MCPNEWS_CONFIG_DIR:-/app/config}" "${MCPNEWS_DATA_DIR:-/data}" \
               "${MCPNEWS_ARCHIVE_DIR:-/archive}"; do
        [ -d "$dir" ] || mkdir -p "$dir"
        # Non-recursive on purpose: files we wrote already belong to us, and a
        # recursive pass over a large archive would delay every restart.
        chown "$APP_USER":"$APP_USER" "$dir" 2>/dev/null || true
    done
    exec su "$APP_USER" -s /bin/sh -c 'exec "$0" "$@"' -- mcpnews "$@"
fi

exec mcpnews "$@"
