# HBA Platform

Internal operations platform for HBA Aesthetics. V1 covers the affiliate
commission and payroll module.

- **Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md`
- **Phase 1 plan:** `docs/plans/2026-08-22-phase-1-platform-foundation.md`

## Local development

```bash
docker compose up -d                       # PostgreSQL on port 5433
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest -v
```

## Principles

Money is integer piastres, never floats. The business month is derived in
`Africa/Cairo`, never a fixed offset. Financial history is appended, never
rewritten — append-only tables are enforced by database triggers.
