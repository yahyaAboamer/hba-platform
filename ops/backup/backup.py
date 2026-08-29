"""Dump the database and upload it to this environment's backup bucket.

Runs as its own Railway cron service - its own container, its own deploy, no
process or memory shared with the app. A bug here can never take the platform
down, and a bug in the platform can never take a backup down with it.

**Why this needs its own image rather than running inside the app.** `pg_dump`
is a Postgres binary, not a Python library - psycopg cannot produce what this
writes. The image is built `FROM postgres:18-alpine`, the same major version
Railway runs, so the tool making the dump is never "probably compatible" with
the database it is dumping - it is the same build.

No secret is ever logged. `DATABASE_URL` and the bucket credentials are read
from the environment and handed straight to `pg_dump` and `boto3`; nothing
about them is printed, including on failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import boto3
from botocore.config import Config


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _client(endpoint: str, access_key: str, secret_key: str, region: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        # Railway Buckets are virtual-hosted-style (the bucket name is a
        # subdomain of the endpoint), which is what this pins rather than
        # leaving to whatever a future botocore version defaults to.
        config=Config(s3={"addressing_style": "virtual"}),
    )


def dump_to(path: str, database_url: str) -> int:
    """Run `pg_dump`, writing Postgres's own custom format - compressed and
    restorable with `pg_restore`, and a fraction of the size of plain SQL.
    """
    result = subprocess.run(
        [
            "pg_dump",
            database_url,
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # pg_dump's own stderr, not the connection string - nothing secret is
        # ever in that message, only what went wrong.
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode)
    return os.path.getsize(path)


def prune(client, bucket: str, prefix: str, keep: int) -> None:
    """Keep the newest `keep` dumps for this environment; delete the rest.

    Filenames are ISO 8601 timestamps, which sort the same alphabetically as
    they do chronologically - so the oldest are found without parsing anything,
    just a string sort.
    """
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    keys.sort()

    doomed = keys[:-keep] if len(keys) > keep else []
    for key in doomed:
        client.delete_object(Bucket=bucket, Key=key)
        print(f"pruned {key}")


def main() -> None:
    database_url = _required("DATABASE_URL")
    bucket = _required("BUCKET")
    endpoint = _required("ENDPOINT")
    access_key = _required("ACCESS_KEY_ID")
    secret_key = _required("SECRET_ACCESS_KEY")
    region = os.environ.get("REGION", "auto").strip() or "auto"
    # Railway names the environment for us; nothing here is typed by hand and
    # nothing here can drift from what the service is actually running in.
    environment = _required("RAILWAY_ENVIRONMENT_NAME")
    keep = int(os.environ.get("BACKUP_KEEP", "30"))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    prefix = f"{environment}/"
    key = f"{prefix}{stamp}.dump"

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "backup.dump")
        print(f"Dumping {environment} ...")
        size = dump_to(path, database_url)
        print(f"Dumped {size:,} bytes. Uploading as {key} ...")

        client = _client(endpoint, access_key, secret_key, region)
        client.upload_file(path, bucket, key)
        print("Uploaded.")

    prune(client, bucket, prefix, keep)
    print("Done.")


if __name__ == "__main__":
    main()
