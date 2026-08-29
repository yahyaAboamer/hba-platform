# The database's own image, not the app's. `pg_dump` is a Postgres binary and
# the version that makes the dump should be the version that runs the
# database - never "close enough". Bump the tag when Railway's Postgres major
# version changes (see docs/operations.md).
FROM postgres:18-alpine

RUN apk add --no-cache python3 py3-pip \
    && pip install --no-cache-dir --break-system-packages boto3==1.*

WORKDIR /backup
COPY backup.py .

# postgres:alpine's own entrypoint exists to start a database server, which
# this container never does - it runs once, dumps, uploads, and exits. Bypass
# it entirely rather than relying on the base image's own logic for
# recognising a non-server command.
ENTRYPOINT ["python3", "backup.py"]
