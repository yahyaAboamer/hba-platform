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
| **What to check when something is wrong** | [`docs/operations.md`](docs/operations.md) — the running-it runbook |
| **How to switch webhooks on** | [`docs/shopify-webhooks.md`](docs/shopify-webhooks.md) — what they are, and the runbook |
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

# 4. Tests  (one at a time - see below)
./.venv/Scripts/python.exe -m pytest -q

# 5. Run it
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

**Run only one pytest process at a time.** Some tests rebuild the schema with
`DROP SCHEMA public CASCADE`, so a second concurrent run - or an `alembic`
command against the same database - deadlocks against it. The failure looks
unrelated to whatever you were changing.

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

## Running the tests

```
pytest
```

**Do not run two pytest processes at once.** The suite empties the database
between tests, so a second run pulls the first one's rows out from under it and
produces failures that look like real bugs. This has cost time more than once.

The suite runs in about **90 seconds**. It used to take fifteen minutes, and the
two reasons are worth knowing because both traps are easy to reintroduce:

**Every test that commits used to rebuild the schema** - drop it, then re-run
every migration - because the append-only guards refuse `TRUNCATE`. That is
2.2 seconds a test across 317 tests. It now empties the tables inside a
transaction with `session_replication_role = replica`, which is 0.2 seconds, and
a test proves the guards are back on afterwards.

**Password hashing is deliberately slow.** 600,000 PBKDF2 iterations is about a
second, and every API test bootstraps an account. The session lowers the count
to 1,000; `test_the_shipped_password_cost_is_not_this_one` reads the source and
asserts what actually ships, so the fast setting cannot leak into production.

