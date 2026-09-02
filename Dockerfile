# One image builds both halves: Python for the API, Node to compile the
# frontend into app/web, which FastAPI then serves.
#
# **Everything here is stated, nothing is inferred.** This file exists because
# on 2026-09-02 Railway's builder upgraded itself to Railpack 0.38.0, stopped
# honouring `[start] cmd` in nixpacks.toml, and refused to guess a start
# command - taking every deploy of both environments down at once, on a commit
# that had built cleanly the day before. Nixpacks was no longer a way back.
# A Dockerfile cannot be upgraded out from under the project, which is the
# whole reason to prefer one here.

FROM python:3.12-slim

# Node is a build-time dependency only - it compiles the frontend and is never
# used at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get purge -y --auto-remove curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency manifests before the source tree, so editing a Python file does
# not reinstall every package. `pyproject.toml` names the package explicitly
# (`include = ["app*"]`), so app/ has to be present for the editable install
# to resolve - it is the only source directory pip needs at this point.
COPY pyproject.toml ./
COPY app ./app
RUN python -m venv --copies /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -e .

# Same reasoning for npm: the lockfile alone, so `npm ci` is cached until a
# dependency actually changes.
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY . .

# Vite is configured to write into app/web, which FastAPI serves as the shell.
# It runs after the full copy because it needs the whole frontend source.
RUN cd frontend && npm run build

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Made executable here rather than relying on the checkout: git on Windows
# does not carry the permission bit, so a mode set locally would not survive
# to the build.
RUN chmod +x /app/docker-entrypoint.sh

# A file, not a string - see docker-entrypoint.sh for why that distinction
# matters to Railway.
CMD ["/app/docker-entrypoint.sh"]
