#!/bin/sh
# The container's start command, as a file rather than a string.
#
# Railway execs the start command directly rather than through a shell, so a
# string containing `&&` - or a leading `.` to activate a venv, as the old
# nixpacks.toml one had - fails with "We don't have permission to execute your
# start command" and no further explanation. A single executable removes the
# question entirely.
set -e

# Migrations run before the server binds, so a deploy that cannot migrate
# fails its health check rather than serving a half-migrated database.
alembic upgrade head

# exec, so uvicorn becomes PID 1 and receives Railway's shutdown signal
# directly instead of it stopping at this script.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
