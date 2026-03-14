#!/usr/bin/env sh

PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-022}
APP_USER=abc
APP_GROUP=abc

log() {
    printf "%s - INFO - init - %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

EXISTING_GROUP=$(getent group "$PGID" 2>/dev/null | cut -d: -f1)
if [ -n "$EXISTING_GROUP" ]; then
    APP_GROUP=$EXISTING_GROUP
elif getent group "$APP_GROUP" >/dev/null 2>&1; then
    groupmod -g "$PGID" "$APP_GROUP"
else
    addgroup -g "$PGID" "$APP_GROUP"
fi

EXISTING_USER=$(getent passwd "$PUID" 2>/dev/null | cut -d: -f1)
if [ -n "$EXISTING_USER" ]; then
    APP_USER=$EXISTING_USER
elif getent passwd "$APP_USER" >/dev/null 2>&1; then
    usermod -u "$PUID" -g "$APP_GROUP" "$APP_USER"
else
    adduser -u "$PUID" -G "$APP_GROUP" -s /bin/sh -D "$APP_USER"
fi

chown -R "$PUID:$PGID" /app
if [ -d "/config" ]; then
    chown -R "$PUID:$PGID" /config
fi

if printf '%s' "$UMASK" | grep -Eq '^[0-7]{3,4}$'; then
    umask "$UMASK"
else
    log "Invalid UMASK '$UMASK' provided, falling back to 022"
    umask 022
fi

CURRENT_UMASK=$(umask)
log "Starting AniBridge (UID: $PUID, GID: $PGID, UMASK: $CURRENT_UMASK)"

exec su-exec "$APP_USER" "$@"
