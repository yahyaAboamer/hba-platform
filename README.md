# HBA Platform

Internal operations platform for HBA Aesthetics. V1 covers the affiliate
commission and payroll module.

## Where things are written down

| | |
|---|---|
| **Why it is built this way** | [`docs/adr/`](docs/adr/README.md) — architecture decision records |
| **What will eventually break** | [`docs/limits.md`](docs/limits.md) — known limits and foreseeable failures |
| **What it does** | [`docs/specs/2026-08-22-hba-platform-v1-design.md`](docs/specs/2026-08-22-hba-platform-v1-design.md) |
| **How it is being built** | [`docs/plans/`](docs/plans) — phase by phase |
| **What changed and when** | the git history |

Start with the ADRs. The code says what the system does; the ADRs say why, and
they are the difference between a deliberate constraint and something that
looks like a mistake.

## Local development

```bash
# 1. Database
docker compose up -d                        # PostgreSQL on port 5433

# 2. Backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -m alembic upgrade head

# 3. Frontend
cd frontend && npm ci && npm run build && cd ..

# 4. Tests
./.venv/Scripts/python.exe -m pytest -q

# 5. Run it
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. On first run, create the administrator:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","display_name":"Your Name","password":"a-long-enough-password"}'
```

Bootstrap works only while no account exists. There is no default password.

While developing the frontend, `cd frontend && npm run dev` gives hot reload
and proxies `/api` to the backend on port 8000.

## Architecture

One service. FastAPI serves the API and the built React bundle from `app/web`,
which keeps hosting to a single deployable. Migrations run at startup, so a
deploy that cannot migrate fails its health check rather than serving a
half-migrated database.

## Principles

Money is integer piastres, never floats, and commission is calculated by
multiplying first and dividing once so no precision is lost across a month of
orders. The business month is derived in `Africa/Cairo`, never a fixed offset,
because Egypt observes daylight saving and an order placed late on the 31st can
belong to either month.

Financial history is appended, never rewritten. Append-only tables are enforced
by database triggers covering `UPDATE`, `DELETE`, **and** `TRUNCATE` — a
row-level trigger alone does not fire on truncate. A consequence worth knowing:
this database cannot be reset, only rebuilt.

Permissions are defined in code and enforced server-side. Hiding a control in
the interface is presentation, not protection.
