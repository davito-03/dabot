#!/bin/sh
set -e
mkdir -p /app/data /app/logs
if [ "$(id -u)" = "0" ]; then
  chown -R dabot:dabot /app/data /app/logs 2>/dev/null || true
  exec gosu dabot "$@"
fi
exec "$@"
