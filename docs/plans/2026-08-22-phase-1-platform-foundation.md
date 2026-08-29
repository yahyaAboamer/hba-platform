# Phase 1: Platform Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the identity, permission, audit, and money/time foundations of the new HBA platform, deployed and healthy on Railway, with nothing affiliate-specific yet.

**Architecture:** A single FastAPI service backed by PostgreSQL. SQLAlchemy 2.0 (synchronous — adequate at this scale and easier to read) with Alembic migrations. Identity is rooted in a generic `user_account` so later modules plug in unchanged. Money is integer piastres with exact-integer commission arithmetic; the business month is derived in `Africa/Cairo`. Append-only tables are enforced by PostgreSQL triggers, not application code. The service also serves a built React bundle so the single-deployable shape is proven end-to-end before any real UI exists.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0, Alembic, psycopg 3, pydantic-settings, pytest, Docker (local Postgres), React 19 + Vite, Railway.

**Spec:** `docs/superpowers/specs/2026-08-22-hba-platform-v1-design.md`

**New repository:** `D:\Desktop\HBA\HBA Engineering\hba-platform` — a fresh git repository. The existing `hba-operations-dashboard` is frozen and is not modified by this plan.

## Global Constraints

- **All money is integer piastres in storage.** No float ever touches a currency value. (Spec §4.7, §9.6)
- **Commission arithmetic is exact.** Multiply before dividing; divide once at the end. Never truncate to piastres mid-chain. (Spec §9.6)
- **Rounding is half-up to whole pounds, once, on the final total.** Never `round()` — Python's built-in uses banker's rounding. Use `Decimal` with `ROUND_HALF_UP`. (Spec §9.6)
- **Timestamps stored in UTC; business month derived in `Africa/Cairo`.** Never a fixed offset — Egypt observes DST. (Spec §7)
- **Permissions and roles are defined in code, assignment happens in data.** No dynamic permission-builder UI. (Spec §6.3)
- **Permission checks are enforced server-side.** Hiding a control is presentation, never protection. (Spec §6.3)
- **Append-only tables reject UPDATE and DELETE at the database level** via trigger. (Spec §4.8, §17)
- **Sensitive fields are masked in audit records.** Account numbers and InstaPay addresses never appear verbatim. (Spec §6.4, §16)
- **No account is ever shared.** (Spec §5.1)
- **English only**, but no user-facing string is hardcoded in a component — all copy lives in one module so Arabic can be added later. (Spec §3)
- **Budget: one Railway service, free-tier Postgres, no Redis.** (Spec §19)
- **Append-only means the database cannot be reset, only rebuilt.** TRUNCATE is
  blocked on audit_event and cascades from other tables are blocked with it. Tests
  needing an empty database use the `fresh_database` fixture, which drops and
  re-migrates the schema. Found while implementing Task 8.
- **Every outbound connection has an explicit timeout.** A probe that hangs is
  worse than one that fails: the health check times out and the platform reports
  nothing useful. Found the hard way in Task 1.

---

## File Structure

```
hba-platform/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, router mounting, static serving
│   ├── config.py                # Settings from environment
│   ├── db.py                    # Engine, session factory, Base
│   ├── core/
│   │   ├── money.py             # Piastres, exact commission, half-up rounding
│   │   ├── businesstime.py      # UTC storage, Africa/Cairo business month
│   │   ├── passwords.py         # PBKDF2 hashing and verification
│   │   └── permissions.py       # Permission constants, role map, has_permission
│   ├── models/
│   │   ├── __init__.py
│   │   ├── identity.py          # user_account, role_assignment, session, invitation
│   │   └── audit.py             # audit_event
│   ├── services/
│   │   ├── auth.py              # Sessions: issue, resolve, revoke
│   │   ├── invitations.py       # Create and accept invitations
│   │   └── audit.py             # record_audit, field masking
│   ├── api/
│   │   ├── deps.py              # current_user, require_permission
│   │   ├── auth.py              # bootstrap, login, logout, me
│   │   └── health.py            # live, ready
│   └── web/                     # built React bundle lands here
├── migrations/                  # Alembic
├── frontend/                    # React + Vite source
├── tests/
├── docker-compose.yml           # local Postgres only
├── pyproject.toml
├── railway.json
└── README.md
```

Each module has one responsibility. `core/` holds pure functions with no database access — they are the most heavily tested and the most reused. `services/` holds business operations. `api/` holds HTTP concerns only.

---

## Task 1: Project skeleton, configuration, and health endpoints

**Files:**
- Create: `hba-platform/pyproject.toml`
- Create: `hba-platform/app/__init__.py`, `hba-platform/app/config.py`, `hba-platform/app/main.py`
- Create: `hba-platform/app/api/__init__.py`, `hba-platform/app/api/health.py`
- Create: `hba-platform/.gitignore`, `hba-platform/README.md`
- Test: `hba-platform/tests/test_health.py`

**Interfaces:**
- Consumes: nothing
- Produces: `app.main:app` (FastAPI instance), `app.config:Settings` with fields `database_url: str`, `app_env: str`, `session_hours: int`

- [ ] **Step 1: Create the project directory and git repository**

```bash
mkdir -p "D:/Desktop/HBA/HBA Engineering/hba-platform"
cd "D:/Desktop/HBA/HBA Engineering/hba-platform"
git init
mkdir -p app/api app/core app/models app/services tests
touch app/__init__.py app/api/__init__.py app/core/__init__.py app/models/__init__.py app/services/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "hba-platform"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.30,<1",
    "sqlalchemy>=2.0,<3",
    "alembic>=1.13,<2",
    "psycopg[binary]>=3.2,<4",
    "pydantic-settings>=2.4,<3",
    "pydantic[email]>=2.9,<3",
    "python-dotenv>=1.0,<2",
    "tzdata>=2025.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.3,<9", "httpx2>=2.9,<3"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`tzdata` is required — Windows has no system timezone database, and `Africa/Cairo` must resolve.

- [ ] **Step 3: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
.pytest_cache/
app/web/
frontend/node_modules/
frontend/dist/
*.log
```

- [ ] **Step 4: Write `app/config.py`**

```python
"""Application settings, read once from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 127.0.0.1 rather than localhost: localhost resolves to both ::1 and
    # 127.0.0.1, so every failed connection is attempted twice.
    database_url: str = "postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform"
    app_env: str = "development"
    session_hours: int = 12
    db_connect_timeout_seconds: int = 5

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


settings = Settings()
```

- [ ] **Step 5: Write `app/api/health.py`**

```python
"""Liveness and readiness probes."""

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db import engine

router = APIRouter()


@router.get("/api/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/api/health/ready")
def ready() -> dict:
    checks: dict = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # surfaced, never swallowed
        checks["database"] = {"ok": False, "error": type(exc).__name__}

    checks["configuration"] = {"ok": True, "environment": settings.app_env}
    ready_now = all(check.get("ok") for check in checks.values())
    return {"status": "ready" if ready_now else "not_ready", "checks": checks}
```

- [ ] **Step 6: Write `app/db.py`**

```python
"""Database engine, session factory, and declarative base."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# libpq defaults connect_timeout to 0, meaning wait forever. An unreachable
# database would then hang the readiness probe instead of failing it, and the
# platform's health check would time out rather than report honestly.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    """FastAPI dependency yielding a database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 7: Write `app/main.py`**

```python
"""HBA Platform — FastAPI application entry point."""

from fastapi import FastAPI

from app.api import health
from app.config import settings

app = FastAPI(
    title="HBA Platform",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.include_router(health.router)
```

- [ ] **Step 8: Write the failing test**

Create `tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_live_returns_ok():
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_database_and_configuration():
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert "database" in body["checks"]
    assert "configuration" in body["checks"]


def test_production_hides_api_docs():
    # Docs must be disabled in production; verified via the app's own config.
    from app.config import Settings

    assert Settings(app_env="production").is_production is True
    assert Settings(app_env="development").is_production is False
```

- [ ] **Step 9: Install and run the tests**

```bash
cd "D:/Desktop/HBA/HBA Engineering/hba-platform"
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -m pytest tests/test_health.py -v
```

Expected: `test_live_returns_ok` and `test_production_hides_api_docs` PASS. `test_ready_reports_database_and_configuration` PASSES with `database.ok == false` because no database is running yet — that is correct behaviour, the probe reports rather than crashes.

- [ ] **Step 10: Commit**

```bash
git add .
git commit -m "feat: project skeleton, settings, and health probes"
```

---

## Task 2: Local PostgreSQL and Alembic migrations

**Files:**
- Create: `hba-platform/docker-compose.yml`
- Create: `hba-platform/alembic.ini`, `hba-platform/migrations/env.py`, `hba-platform/migrations/script.py.mako`
- Test: `hba-platform/tests/test_migrations.py`

**Interfaces:**
- Consumes: `app.db:Base`, `app.config:settings`
- Produces: a migrated database; `alembic upgrade head` as the deployment migration command

- [ ] **Step 1: Write `docker-compose.yml`**

Port 5433 avoids colliding with any Postgres already on 5432.

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: hba
      POSTGRES_PASSWORD: hba
      POSTGRES_DB: hba_platform
    ports:
      - "5433:5432"
    volumes:
      - hba_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U hba -d hba_platform"]
      interval: 5s
      retries: 10

volumes:
  hba_pgdata:
```

- [ ] **Step 2: Start the database and confirm it is healthy**

```bash
docker compose up -d
docker compose ps
```

Expected: the `postgres` service shows state `running` and health `healthy`.

- [ ] **Step 3: Initialise Alembic**

```bash
./.venv/Scripts/python.exe -m alembic init migrations
```

- [ ] **Step 4: Point Alembic at the application settings**

Replace the whole of `migrations/env.py` with:

```python
"""Alembic environment — reads the URL from application settings."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db import Base
import app.models  # noqa: F401  — ensures every model is imported and registered

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5: Write `app/models/__init__.py`**

Empty for now; later tasks add imports so Alembic sees every table.

```python
"""Model registry. Every model module must be imported here for Alembic autogenerate."""
```

- [ ] **Step 6: Write the failing test**

Create `tests/test_migrations.py`:

```python
from sqlalchemy import text

from app.db import engine


def test_database_is_reachable():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar() == 1


def test_alembic_version_table_exists_after_upgrade():
    with engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'alembic_version'"
            )
        ).scalar()
    assert result == 1, "run: alembic upgrade head"
```

- [ ] **Step 7: Run the test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_migrations.py -v
```

Expected: `test_database_is_reachable` PASSES, `test_alembic_version_table_exists_after_upgrade` FAILS — no migration has run.

- [ ] **Step 8: Create and apply an initial empty revision**

```bash
./.venv/Scripts/python.exe -m alembic revision -m "initial"
./.venv/Scripts/python.exe -m alembic upgrade head
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_migrations.py -v
```

Expected: both PASS.

- [ ] **Step 10: Commit**

```bash
git add .
git commit -m "feat: local Postgres via Docker and Alembic migrations"
```

---

## Task 3: Money — integer piastres and exact commission arithmetic

This is the most important pure module in the system. Every rule here comes from spec §9.6.

**Files:**
- Create: `hba-platform/app/core/money.py`
- Test: `hba-platform/tests/test_money.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `commission_numerator(base_piastres: int, rate_bp: int) -> int`
  - `exact_commission_piastres(numerator_total: int) -> Decimal`
  - `round_half_up_to_pounds(exact_piastres: Decimal) -> int` (returns piastres, always a multiple of 100)
  - `format_egp(piastres: int) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_money.py`:

```python
from decimal import Decimal

import pytest

from app.core.money import (
    commission_numerator,
    exact_commission_piastres,
    format_egp,
    round_half_up_to_pounds,
)


def test_numerator_multiplies_without_dividing():
    # 106,237 piastres at 10% (1000 basis points)
    assert commission_numerator(106_237, 1000) == 106_237_000


def test_exact_commission_keeps_the_fractional_piastre():
    # 106,237,000 / 10,000 = 10,623.7 piastres — the fraction must survive
    exact = exact_commission_piastres(106_237_000)
    assert exact == Decimal("10623.7")


def test_summing_before_dividing_loses_nothing():
    # Three orders that each produce a fractional piastre individually.
    orders = [(106_237, 1000), (33_333, 1000), (66_667, 1000)]
    total = sum(commission_numerator(base, rate) for base, rate in orders)
    exact = exact_commission_piastres(total)
    # 106237 + 33333 + 66667 = 206237 piastres; at 10% that is 20623.7 piastres exactly
    assert exact == Decimal("20623.7")


def test_rounds_half_up_not_bankers():
    # E£10,608.50 must round UP to E£10,609. Python's round() would give 10,608.
    assert round_half_up_to_pounds(Decimal("1060850")) == 1_060_900
    assert round(Decimal("10608.50")) == 10608  # proves why we cannot use round()


def test_rounds_down_below_half():
    # E£10,608.37 rounds down to E£10,608
    assert round_half_up_to_pounds(Decimal("1060837")) == 1_060_800


def test_rounds_up_above_half():
    # E£10,608.61 rounds up to E£10,609
    assert round_half_up_to_pounds(Decimal("1060861")) == 1_060_900


def test_rounded_result_is_always_whole_pounds():
    for value in ["0", "1", "49", "50", "51", "1060837", "999999"]:
        assert round_half_up_to_pounds(Decimal(value)) % 100 == 0


def test_zero_and_negative_are_handled():
    assert round_half_up_to_pounds(Decimal("0")) == 0
    # Negative arises from credits and write-offs; -E£0.50 rounds away from zero.
    assert round_half_up_to_pounds(Decimal("-50")) == -100


def test_rate_must_be_within_range():
    with pytest.raises(ValueError):
        commission_numerator(1000, 0)
    with pytest.raises(ValueError):
        commission_numerator(1000, 10_001)


def test_base_must_not_be_negative():
    with pytest.raises(ValueError):
        commission_numerator(-1, 1000)


def test_format_egp_uses_thousands_and_two_decimals():
    assert format_egp(1_060_837) == "E£10,608.37"
    assert format_egp(0) == "E£0.00"
    assert format_egp(-1_060_837) == "-E£10,608.37"


def test_order_29115_from_the_spec():
    # Customer paid E£1,157.00, of which E£95.00 was shipping.
    # Commission base is E£1,062.00 = 106,200 piastres. At 10%: E£106.20
    base = 115_700 - 9_500
    assert base == 106_200
    exact = exact_commission_piastres(commission_numerator(base, 1000))
    assert exact == Decimal("10620")
    assert round_half_up_to_pounds(exact) == 10_600  # E£106.00
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_money.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.money'`

- [ ] **Step 3: Write the implementation**

Create `app/core/money.py`:

```python
"""Money primitives.

Every currency amount in this system is an integer number of piastres
(1 EGP = 100 piastres). Floating point never touches money.

Commission is calculated by multiplying first and dividing once, at the very
end, so no precision is lost across an arbitrary number of orders. Rounding to
whole pounds happens exactly once, on the final payout total, using half-up.
"""

from decimal import ROUND_HALF_UP, Decimal

BASIS_POINTS = 10_000
PIASTRES_PER_POUND = 100


def commission_numerator(base_piastres: int, rate_bp: int) -> int:
    """Return base x rate as an exact integer, deliberately undivided.

    Callers sum these across every order in a month and divide only once,
    via exact_commission_piastres. This makes the arithmetic exact regardless
    of how many orders are involved.
    """
    if base_piastres < 0:
        raise ValueError("Commission base cannot be negative")
    if not 0 < rate_bp <= BASIS_POINTS:
        raise ValueError("Commission rate must be above 0 and at most 10000 basis points")
    return base_piastres * rate_bp


def exact_commission_piastres(numerator_total: int) -> Decimal:
    """Divide the summed numerator once, preserving fractional piastres."""
    return Decimal(numerator_total) / Decimal(BASIS_POINTS)


def round_half_up_to_pounds(exact_piastres: Decimal) -> int:
    """Round to whole pounds, half-up, and return the result in piastres.

    Half-up, not banker's rounding: E£10,608.50 becomes E£10,609. Python's
    built-in round() would return E£10,608, which is why it is never used here.
    """
    pounds = (Decimal(exact_piastres) / PIASTRES_PER_POUND).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(pounds) * PIASTRES_PER_POUND


def format_egp(piastres: int) -> str:
    """Render piastres as a display string. Never used for calculation."""
    sign = "-" if piastres < 0 else ""
    whole, fraction = divmod(abs(int(piastres)), PIASTRES_PER_POUND)
    return f"{sign}E£{whole:,}.{fraction:02d}"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_money.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/money.py tests/test_money.py
git commit -m "feat: exact integer money arithmetic with half-up rounding"
```

---

## Task 4: Business time — UTC storage, Africa/Cairo months

Spec §7. This decides which payroll month an order belongs to, so it is a financial rule.

**Files:**
- Create: `hba-platform/app/core/businesstime.py`
- Test: `hba-platform/tests/test_businesstime.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `BUSINESS_TIMEZONE: ZoneInfo`
  - `business_month(moment_utc: datetime) -> str` returning `"YYYY-MM"`
  - `business_date(moment_utc: datetime) -> date`
  - `utcnow() -> datetime` (timezone-aware)
  - `parse_month(value: str) -> str` validating `YYYY-MM`
  - `month_add(month: str, delta: int) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_businesstime.py`:

```python
from datetime import datetime, timezone

import pytest

from app.core.businesstime import (
    business_date,
    business_month,
    month_add,
    parse_month,
    utcnow,
)


def test_utcnow_is_timezone_aware():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None


def test_naive_datetime_is_rejected():
    # A naive timestamp has no defined instant; guessing would corrupt payroll.
    with pytest.raises(ValueError):
        business_month(datetime(2026, 8, 31, 21, 30))


def test_summer_order_late_at_night_belongs_to_the_next_month():
    # Egypt observes DST (UTC+3) in August 2026.
    # 21:30 UTC on 31 Aug is 00:30 on 1 Sep in Cairo.
    moment = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)
    assert business_month(moment) == "2026-09"


def test_summer_order_earlier_the_same_evening_stays_in_august():
    # 20:00 UTC is 23:00 Cairo on 31 Aug — still August.
    moment = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
    assert business_month(moment) == "2026-08"


def test_winter_order_uses_the_standard_offset():
    # Egypt is UTC+2 in December. 22:30 UTC on 31 Dec is 00:30 on 1 Jan.
    moment = datetime(2026, 12, 31, 22, 30, tzinfo=timezone.utc)
    assert business_month(moment) == "2027-01"


def test_winter_order_before_the_boundary_stays_in_december():
    moment = datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc)
    assert business_month(moment) == "2026-12"


def test_a_fixed_offset_would_get_it_wrong():
    """Proves why a hardcoded UTC+2 is unacceptable."""
    from datetime import timedelta

    moment = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)
    naive_plus_two = (moment + timedelta(hours=2)).strftime("%Y-%m")
    assert naive_plus_two == "2026-08"          # wrong
    assert business_month(moment) == "2026-09"  # correct


def test_business_date_matches_the_month():
    moment = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)
    assert business_date(moment).isoformat() == "2026-09-01"


def test_parse_month_accepts_valid_and_rejects_invalid():
    assert parse_month("2026-08") == "2026-08"
    for bad in ["2026-13", "2026-00", "26-08", "2026-8", "", "2026-08-01"]:
        with pytest.raises(ValueError):
            parse_month(bad)


def test_month_add_crosses_year_boundaries():
    assert month_add("2026-08", 1) == "2026-09"
    assert month_add("2026-12", 1) == "2027-01"
    assert month_add("2026-01", -1) == "2025-12"
    assert month_add("2026-08", 0) == "2026-08"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_businesstime.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.businesstime'`

- [ ] **Step 3: Write the implementation**

Create `app/core/businesstime.py`:

```python
"""Business time rules.

Timestamps are stored in UTC. The business month — which decides which payroll
period an order belongs to, and therefore who is paid what — is derived in
Africa/Cairo.

A fixed offset is never used. Egypt reinstated seasonal clock changes in 2023,
so both UTC+2 and UTC+3 occur within a single year, and an order placed late in
the evening can fall on either side of a month boundary depending on the date.
"""

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Africa/Cairo")
_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def utcnow() -> datetime:
    """Current instant, timezone-aware, in UTC."""
    return datetime.now(timezone.utc)


def _require_aware(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Business time requires a timezone-aware datetime")
    return moment


def business_date(moment_utc: datetime) -> date:
    """The calendar date in Cairo for a given instant."""
    return _require_aware(moment_utc).astimezone(BUSINESS_TIMEZONE).date()


def business_month(moment_utc: datetime) -> str:
    """The YYYY-MM business month in Cairo for a given instant."""
    return business_date(moment_utc).strftime("%Y-%m")


def parse_month(value: str) -> str:
    """Validate a YYYY-MM month string, returning it unchanged."""
    if not isinstance(value, str) or not _MONTH_PATTERN.match(value):
        raise ValueError("Month must use YYYY-MM format")
    return value


def month_add(month: str, delta: int) -> str:
    """Shift a YYYY-MM month by a number of months, crossing years correctly."""
    parse_month(month)
    year, mon = (int(part) for part in month.split("-"))
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_businesstime.py -v
```

Expected: all 10 tests PASS. If `ZoneInfoNotFoundError` appears, `tzdata` is missing — reinstall dependencies.

- [ ] **Step 5: Commit**

```bash
git add app/core/businesstime.py tests/test_businesstime.py
git commit -m "feat: Cairo business-month derivation with DST correctness"
```

---

## Task 5: Password hashing

**Files:**
- Create: `hba-platform/app/core/passwords.py`
- Test: `hba-platform/tests/test_passwords.py`

**Interfaces:**
- Consumes: nothing
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, encoded: str) -> bool`, `MINIMUM_PASSWORD_LENGTH: int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_passwords.py`:

```python
import pytest

from app.core.passwords import MINIMUM_PASSWORD_LENGTH, hash_password, verify_password


def test_correct_password_verifies():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded) is True


def test_wrong_password_fails():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("incorrect horse battery staple", encoded) is False


def test_same_password_produces_different_hashes():
    # A random salt per hash means identical passwords never collide.
    assert hash_password("a-long-enough-password") != hash_password("a-long-enough-password")


def test_short_passwords_are_rejected():
    with pytest.raises(ValueError):
        hash_password("a" * (MINIMUM_PASSWORD_LENGTH - 1))


def test_minimum_length_is_accepted():
    encoded = hash_password("a" * MINIMUM_PASSWORD_LENGTH)
    assert verify_password("a" * MINIMUM_PASSWORD_LENGTH, encoded) is True


def test_malformed_hash_returns_false_rather_than_raising():
    for bad in ["", "nonsense", "pbkdf2_sha256$notanumber$salt$hash"]:
        assert verify_password("anything", bad) is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_passwords.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the implementation**

Create `app/core/passwords.py`:

```python
"""Password hashing using PBKDF2-HMAC-SHA256 from the standard library.

600,000 iterations follows current OWASP guidance for PBKDF2-SHA256. Using the
standard library keeps the dependency surface small and the code readable by
the person who maintains it.
"""

import base64
import hashlib
import hmac
import os

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16
MINIMUM_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password or "") < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} characters"
        )
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "$".join(
        [
            ALGORITHM,
            str(ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification. Malformed input returns False, never raises."""
    try:
        algorithm, iterations, salt_b64, digest_b64 = str(encoded).split("$")
        if algorithm != ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_passwords.py -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/passwords.py tests/test_passwords.py
git commit -m "feat: PBKDF2 password hashing"
```

---

## Task 6: Permissions defined in code

Spec §5.1 and §6.3. Roles are code, assignment is data.

**Files:**
- Create: `hba-platform/app/core/permissions.py`
- Test: `hba-platform/tests/test_permissions.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Permission` (str constants class), `ROLES: dict[str, frozenset[str]]`, `has_permission(role: str, permission: str) -> bool`, `permissions_for(role: str) -> frozenset[str]`, `VALID_ROLES: frozenset[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_permissions.py`:

```python
import pytest

from app.core.permissions import (
    ROLES,
    VALID_ROLES,
    Permission,
    has_permission,
    permissions_for,
)


def test_admin_has_every_permission():
    every = {value for name, value in vars(Permission).items() if not name.startswith("_")}
    for permission in every:
        assert has_permission("admin", permission) is True


def test_affiliate_manager_can_run_payroll_but_not_record_payments():
    assert has_permission("affiliate_manager", Permission.PAYROLL_APPROVE) is True
    assert has_permission("affiliate_manager", Permission.COMPENSATION_MANAGE) is True
    assert has_permission("affiliate_manager", Permission.INVITATIONS_SEND) is True
    # Payment recording stays with admin at launch (spec 5.1).
    assert has_permission("affiliate_manager", Permission.PAYMENTS_RECORD) is False


def test_target_recorder_can_only_record_targets():
    assert has_permission("target_recorder", Permission.TARGETS_RECORD) is True
    assert has_permission("target_recorder", Permission.AFFILIATES_VIEW) is True
    # The whole point of this role: no financial authority whatsoever.
    for forbidden in (
        Permission.COMPENSATION_MANAGE,
        Permission.PAYROLL_APPROVE,
        Permission.PAYROLL_REOPEN,
        Permission.PAYMENTS_RECORD,
        Permission.INVITATIONS_SEND,
        Permission.AFFILIATES_MANAGE,
        Permission.TARGETS_VERIFY,
    ):
        assert has_permission("target_recorder", forbidden) is False


def test_affiliate_role_has_no_staff_permissions():
    assert permissions_for("affiliate") == frozenset()


def test_unknown_role_grants_nothing():
    assert has_permission("wizard", Permission.AFFILIATES_VIEW) is False
    assert permissions_for("wizard") == frozenset()


def test_unknown_permission_is_rejected_even_for_admin():
    with pytest.raises(ValueError):
        has_permission("admin", "not.a.real.permission")


def test_valid_roles_matches_the_role_map():
    assert VALID_ROLES == frozenset(ROLES)


def test_every_granted_permission_is_a_real_permission():
    every = {value for name, value in vars(Permission).items() if not name.startswith("_")}
    for role, granted in ROLES.items():
        assert granted <= every, f"{role} grants an unknown permission"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_permissions.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the implementation**

Create `app/core/permissions.py`:

```python
"""Permissions and roles, defined in code.

Roles are deliberately not composable through the interface. Defining them here
means every change to who can do what is version-controlled, reviewed, and
covered by tests. Assigning a person to a role happens in the application; that
is the flexibility that is actually needed day to day.
"""


class Permission:
    AFFILIATES_VIEW = "affiliates.view"
    AFFILIATES_MANAGE = "affiliates.manage"
    COMPENSATION_MANAGE = "compensation.manage"
    TARGETS_RECORD = "targets.record"
    TARGETS_MANAGE = "targets.manage"
    TARGETS_VERIFY = "targets.verify"
    PAYROLL_APPROVE = "payroll.approve"
    PAYROLL_REOPEN = "payroll.reopen"
    PAYMENTS_RECORD = "payments.record"
    INVITATIONS_SEND = "invitations.send"
    AUDIT_VIEW = "audit.view"
    SETTINGS_MANAGE = "settings.manage"


ALL_PERMISSIONS = frozenset(
    value for name, value in vars(Permission).items() if not name.startswith("_")
)

ROLES: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "affiliate_manager": frozenset(
        {
            Permission.AFFILIATES_VIEW,
            Permission.AFFILIATES_MANAGE,
            Permission.COMPENSATION_MANAGE,
            Permission.TARGETS_RECORD,
            Permission.TARGETS_MANAGE,
            Permission.TARGETS_VERIFY,
            Permission.PAYROLL_APPROVE,
            Permission.INVITATIONS_SEND,
            Permission.AUDIT_VIEW,
        }
    ),
    # Sara records video and story counts. They need nothing else, so they get
    # nothing else — the audit trail is only meaningful when access is minimal.
    "target_recorder": frozenset(
        {
            Permission.AFFILIATES_VIEW,
            Permission.TARGETS_RECORD,
        }
    ),
    # Affiliates reach only their own portal, which is authorised by ownership
    # of the record rather than by any staff permission.
    "affiliate": frozenset(),
}

VALID_ROLES = frozenset(ROLES)


def permissions_for(role: str) -> frozenset[str]:
    return ROLES.get(role, frozenset())


def has_permission(role: str, permission: str) -> bool:
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")
    return permission in permissions_for(role)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_permissions.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/permissions.py tests/test_permissions.py
git commit -m "feat: code-defined permissions and roles"
```

---

## Task 7: Identity schema — user_account, role_assignment, session, invitation

Spec §6.1. Identity is generic; affiliates hang off it later.

**Files:**
- Create: `hba-platform/app/models/identity.py`
- Modify: `hba-platform/app/models/__init__.py`
- Create: migration via Alembic autogenerate
- Test: `hba-platform/tests/test_identity_models.py`, `hba-platform/tests/conftest.py`

**Interfaces:**
- Consumes: `app.db:Base`, `app.core.businesstime:utcnow`
- Produces: `UserAccount`, `RoleAssignment`, `AuthSession`, `Invitation` ORM classes; `tests/conftest.py` providing a `db` fixture

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import pytest
from sqlalchemy import text

from app.db import SessionLocal, engine


@pytest.fixture()
def db():
    """A session wrapped in a transaction that is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def clean_tables():
    """Truncate identity tables. Used only by tests that need real commits."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE invitation, auth_session, role_assignment, user_account "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_identity_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.businesstime import utcnow
from app.models.identity import AuthSession, Invitation, RoleAssignment, UserAccount


def test_user_account_can_be_created(db):
    user = UserAccount(email="owner@example.com", password_hash="x", status="active")
    db.add(user)
    db.flush()
    assert user.id is not None
    assert user.created_at is not None


def test_email_is_unique_case_insensitively(db):
    db.add(UserAccount(email="owner@example.com", password_hash="x", status="active"))
    db.flush()
    db.add(UserAccount(email="OWNER@EXAMPLE.COM", password_hash="y", status="active"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_role_assignment_links_to_a_user(db):
    user = UserAccount(email="staff@example.com", password_hash="x", status="active")
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role="target_recorder"))
    db.flush()
    assert db.query(RoleAssignment).filter_by(user_account_id=user.id).count() == 1


def test_invalid_role_is_rejected_by_the_database(db):
    user = UserAccount(email="staff2@example.com", password_hash="x", status="active")
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role="wizard"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_session_stores_hashes_not_tokens(db):
    user = UserAccount(email="s@example.com", password_hash="x", status="active")
    db.add(user)
    db.flush()
    session_row = AuthSession(
        user_account_id=user.id,
        token_hash="a" * 64,
        csrf_hash="b" * 64,
        expires_at=utcnow(),
    )
    db.add(session_row)
    db.flush()
    # There is no column that could hold a raw token.
    assert not hasattr(session_row, "token")


def test_invitation_requires_a_valid_role(db):
    db.add(
        Invitation(
            email="new@example.com",
            role="not_a_role",
            token_hash="c" * 64,
            expires_at=utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_identity_models.py -v
```

Expected: FAIL — `app.models.identity` does not exist.

- [ ] **Step 4: Write the models**

Create `app/models/identity.py`:

```python
"""Identity spine.

Identity is rooted in user_account, not in any business record. Staff exist as
user accounts today; affiliates will hang an affiliate_profile off the same
table in a later phase, and Production and Operations staff will do the same
without any change here.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.permissions import VALID_ROLES
from app.db import Base

_ROLE_LIST = ", ".join(f"'{role}'" for role in sorted(VALID_ROLES))
_STATUS_LIST = "'invited', 'active', 'suspended'"


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="user_account_status_valid"),
        Index("user_account_email_lower_key", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="invited")
    display_name: Mapped[str | None] = mapped_column(String(120))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    roles: Mapped[list["RoleAssignment"]] = relationship(back_populates="user")


class RoleAssignment(Base):
    __tablename__ = "role_assignment"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_LIST})", name="role_assignment_role_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["UserAccount"] = relationship(
        back_populates="roles", foreign_keys=[user_account_id]
    )


class AuthSession(Base):
    """A browser session. Only hashes are stored; raw tokens live in cookies."""

    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Invitation(Base):
    """A single-use invitation. There is no public staff signup."""

    __tablename__ = "invitation"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_LIST})", name="invitation_role_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```

- [ ] **Step 5: Register the models with Alembic**

Replace `app/models/__init__.py` with:

```python
"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.models import identity  # noqa: F401
```

- [ ] **Step 6: Generate and apply the migration**

```bash
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "identity spine"
./.venv/Scripts/python.exe -m alembic upgrade head
```

Open the generated file under `migrations/versions/` and confirm it creates all four tables plus the unique lower(email) index. If the index is missing, add it manually:

```python
op.create_index(
    "user_account_email_lower_key",
    "user_account",
    [sa.text("lower(email)")],
    unique=True,
)
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_identity_models.py -v
```

Expected: all 6 PASS.

- [ ] **Step 8: Commit**

```bash
git add app/models tests/test_identity_models.py tests/conftest.py migrations/
git commit -m "feat: identity spine schema with database-enforced role validity"
```

---

## Task 8: Append-only audit log with database-enforced immutability

Spec §4.8, §16, §17. The trigger is the point — application code is not the last line of defence.

**Files:**
- Create: `hba-platform/app/models/audit.py`, `hba-platform/app/services/audit.py`
- Modify: `hba-platform/app/models/__init__.py`
- Create: a hand-written Alembic migration for the trigger
- Test: `hba-platform/tests/test_audit.py`

**Interfaces:**
- Consumes: `app.db:Base`, `app.core.businesstime:utcnow`
- Produces: `AuditEvent` model; `record_audit(db, *, action, actor_id, subject, before=None, after=None, reason=None, ip_address=None) -> AuditEvent`; `mask_sensitive(payload: dict) -> dict`; `SENSITIVE_FIELDS: frozenset[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit.py`:

```python
import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.models.audit import AuditEvent
from app.models.identity import UserAccount
from app.services.audit import SENSITIVE_FIELDS, mask_sensitive, record_audit


def test_masking_hides_account_identifiers():
    masked = mask_sensitive(
        {
            "name": "Nour Adel",
            "instapay_address_url": "https://ipn.eg/nour@instapay",
            "bank_account_number": "EG380003000123456789",
            "wallet_phone": "01012345678",
        }
    )
    assert masked["name"] == "Nour Adel"
    for field in ("instapay_address_url", "bank_account_number", "wallet_phone"):
        assert masked[field] != "…"  # something is shown
        assert "0003000123456789" not in str(masked[field])
        assert "nour@instapay" not in str(masked[field])


def test_masking_is_recursive():
    masked = mask_sensitive({"destination": {"bank_account_number": "EG3800030001234"}})
    assert "0003000123" not in str(masked["destination"]["bank_account_number"])


def test_every_sensitive_field_is_masked():
    payload = {field: "SECRETVALUE12345" for field in SENSITIVE_FIELDS}
    masked = mask_sensitive(payload)
    for field in SENSITIVE_FIELDS:
        assert "SECRETVALUE12345" not in str(masked[field])


def test_record_audit_writes_a_row(db):
    actor = UserAccount(email="a@example.com", password_hash="x", status="active")
    db.add(actor)
    db.flush()
    event = record_audit(
        db,
        action="user.login",
        actor_id=actor.id,
        subject=f"user:{actor.id}",
        after={"email": "a@example.com"},
    )
    db.flush()
    assert event.id is not None
    assert event.action == "user.login"


def test_record_audit_masks_before_storing(db):
    actor = UserAccount(email="b@example.com", password_hash="x", status="active")
    db.add(actor)
    db.flush()
    event = record_audit(
        db,
        action="payout_destination.change",
        actor_id=actor.id,
        subject="affiliate:1",
        after={"bank_account_number": "EG380003000123456789"},
    )
    db.flush()
    assert "0003000123456789" not in str(event.after_json)


def test_audit_rows_cannot_be_updated(db):
    actor = UserAccount(email="c@example.com", password_hash="x", status="active")
    db.add(actor)
    db.flush()
    event = record_audit(db, action="x.y", actor_id=actor.id, subject="s")
    db.flush()
    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(
            text("UPDATE audit_event SET action = 'tampered' WHERE id = :i"),
            {"i": event.id},
        )


def test_audit_rows_cannot_be_deleted(db):
    actor = UserAccount(email="d@example.com", password_hash="x", status="active")
    db.add(actor)
    db.flush()
    event = record_audit(db, action="x.y", actor_id=actor.id, subject="s")
    db.flush()
    with pytest.raises((InternalError, ProgrammingError)):
        db.execute(text("DELETE FROM audit_event WHERE id = :i"), {"i": event.id})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_audit.py -v
```

Expected: FAIL — `app.models.audit` does not exist.

- [ ] **Step 3: Write the model**

Create `app/models/audit.py`:

```python
"""Append-only business audit trail."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    actor_email: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
```

- [ ] **Step 4: Write the service**

Create `app/services/audit.py`:

```python
"""Recording audit events, with sensitive values masked before storage."""

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent

SENSITIVE_FIELDS = frozenset(
    {
        "instapay_address_url",
        "instapay_phone",
        "bank_account_number",
        "bank_account_holder",
        "wallet_phone",
        "password",
        "password_hash",
        "token",
        "token_hash",
    }
)


def _mask_value(value: Any) -> str:
    """Show only enough to recognise a value, never enough to reuse it."""
    text_value = str(value or "")
    if len(text_value) <= 4:
        return "****"
    return f"****{text_value[-4:]}"


def mask_sensitive(payload: Any) -> Any:
    """Recursively mask sensitive fields in a dictionary destined for the audit log."""
    if isinstance(payload, dict):
        return {
            key: (_mask_value(value) if key in SENSITIVE_FIELDS else mask_sensitive(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [mask_sensitive(item) for item in payload]
    return payload


def record_audit(
    db: Session,
    *,
    action: str,
    subject: str,
    actor_id: int | None = None,
    actor_email: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        action=action,
        subject=subject,
        actor_id=actor_id,
        actor_email=actor_email,
        before_json=mask_sensitive(before) if before is not None else None,
        after_json=mask_sensitive(after) if after is not None else None,
        reason=reason,
        ip_address=ip_address,
    )
    db.add(event)
    return event
```

- [ ] **Step 5: Register the model**

Replace `app/models/__init__.py` with:

```python
"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.models import audit, identity  # noqa: F401
```

- [ ] **Step 6: Generate the table migration, then hand-write the trigger migration**

```bash
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "audit event table"
./.venv/Scripts/python.exe -m alembic revision -m "append only audit trigger"
```

In the second generated file, fill in `upgrade()` and `downgrade()`:

```python
def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'append-only table: % rows cannot be % ',
                TG_TABLE_NAME, lower(TG_OP);
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER audit_event_no_update_or_delete
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();

        -- A row-level trigger does NOT fire on TRUNCATE. Verified against
        -- Postgres: without this statement-level guard, one TRUNCATE erases
        -- the entire audit trail silently.
        CREATE TRIGGER audit_event_no_truncate
        BEFORE TRUNCATE ON audit_event
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_append_only ON audit_event;")
    op.execute("DROP FUNCTION IF EXISTS reject_mutation();")
```

`reject_mutation()` is written once and reused by every append-only table added in later phases.

- [ ] **Step 7: Apply the migrations**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_audit.py -v
```

Expected: all 7 PASS. The final two prove the database itself refuses tampering.

- [ ] **Step 9: Commit**

```bash
git add app/models tests/test_audit.py app/services/audit.py migrations/
git commit -m "feat: append-only audit log enforced by database trigger"
```

---

## Task 9: Sessions and invitations

**Files:**
- Create: `hba-platform/app/services/auth.py`, `hba-platform/app/services/invitations.py`
- Test: `hba-platform/tests/test_auth_service.py`, `hba-platform/tests/test_invitations.py`

**Interfaces:**
- Consumes: `app.models.identity`, `app.core.passwords`, `app.core.businesstime:utcnow`, `app.core.permissions:VALID_ROLES`
- Produces:
  - `issue_session(db, user_id, ip=None, user_agent=None) -> tuple[str, str, AuthSession]` returning `(token, csrf, row)`
  - `resolve_session(db, token, csrf=None) -> UserAccount | None`
  - `revoke_session(db, token) -> bool`
  - `authenticate(db, email, password) -> UserAccount | None`
  - `create_invitation(db, email, role, invited_by, hours=72) -> tuple[str, Invitation]`
  - `accept_invitation(db, token, password, display_name) -> UserAccount`

- [ ] **Step 1: Write the failing tests for sessions**

Create `tests/test_auth_service.py`:

```python
from datetime import timedelta

from app.core.businesstime import utcnow
from app.core.passwords import hash_password
from app.models.identity import AuthSession, UserAccount
from app.services.auth import authenticate, issue_session, resolve_session, revoke_session


def _user(db, email="u@example.com", password="a-long-enough-password"):
    user = UserAccount(
        email=email, password_hash=hash_password(password), status="active"
    )
    db.add(user)
    db.flush()
    return user


def test_issued_session_resolves(db):
    user = _user(db)
    token, csrf, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, token, csrf).id == user.id


def test_raw_token_is_never_stored(db):
    user = _user(db)
    token, _, row = issue_session(db, user.id)
    db.flush()
    assert row.token_hash != token
    assert len(row.token_hash) == 64


def test_wrong_csrf_is_rejected(db):
    user = _user(db)
    token, _, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, token, "wrong-csrf") is None


def test_csrf_is_not_required_for_reads(db):
    user = _user(db)
    token, _, _ = issue_session(db, user.id)
    db.flush()
    assert resolve_session(db, token, None).id == user.id


def test_expired_session_is_rejected(db):
    user = _user(db)
    token, csrf, row = issue_session(db, user.id)
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.flush()
    assert resolve_session(db, token, csrf) is None


def test_revoked_session_is_rejected(db):
    user = _user(db)
    token, csrf, _ = issue_session(db, user.id)
    db.flush()
    assert revoke_session(db, token) is True
    db.flush()
    assert resolve_session(db, token, csrf) is None


def test_suspended_user_cannot_resolve(db):
    user = _user(db, email="susp@example.com")
    token, csrf, _ = issue_session(db, user.id)
    user.status = "suspended"
    db.flush()
    assert resolve_session(db, token, csrf) is None


def test_authenticate_accepts_correct_password(db):
    _user(db, email="auth@example.com", password="a-long-enough-password")
    assert authenticate(db, "auth@example.com", "a-long-enough-password") is not None


def test_authenticate_is_case_insensitive_on_email(db):
    _user(db, email="Case@Example.com", password="a-long-enough-password")
    assert authenticate(db, "case@example.com", "a-long-enough-password") is not None


def test_authenticate_rejects_wrong_password_and_unknown_email(db):
    _user(db, email="auth2@example.com", password="a-long-enough-password")
    assert authenticate(db, "auth2@example.com", "wrong-password-here") is None
    assert authenticate(db, "nobody@example.com", "a-long-enough-password") is None


def test_authenticate_rejects_suspended_user(db):
    user = _user(db, email="auth3@example.com", password="a-long-enough-password")
    user.status = "suspended"
    db.flush()
    assert authenticate(db, "auth3@example.com", "a-long-enough-password") is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_auth_service.py -v
```

Expected: FAIL — `app.services.auth` does not exist.

- [ ] **Step 3: Write `app/services/auth.py`**

```python
"""Sessions and authentication.

Only hashes are stored. The raw session token lives in an HttpOnly cookie and
the CSRF token in a response header, so a database leak cannot be replayed as a
login.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.core.passwords import verify_password
from app.models.identity import AuthSession, UserAccount

TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(
    db: Session,
    user_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str, AuthSession]:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    csrf = secrets.token_urlsafe(TOKEN_BYTES)
    row = AuthSession(
        user_account_id=user_id,
        token_hash=_hash(token),
        csrf_hash=_hash(csrf),
        expires_at=utcnow() + timedelta(hours=settings.session_hours),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(row)
    return token, csrf, row


def resolve_session(
    db: Session, token: str, csrf: str | None = None
) -> UserAccount | None:
    """Return the account for a session token, or None if it is not usable.

    When csrf is provided it must match. Callers pass None for safe methods and
    the submitted header value for unsafe ones.
    """
    if not token:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        return None
    if csrf is not None and not hmac.compare_digest(row.csrf_hash, _hash(csrf)):
        return None
    user = db.get(UserAccount, row.user_account_id)
    if user is None or user.status != "active":
        return None
    row.last_seen_at = utcnow()
    return user


def revoke_session(db: Session, token: str) -> bool:
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash(token)))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    return True


def authenticate(db: Session, email: str, password: str) -> UserAccount | None:
    user = db.scalar(
        select(UserAccount).where(func.lower(UserAccount.email) == (email or "").lower())
    )
    if user is None or user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    return user
```

- [ ] **Step 4: Run to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_auth_service.py -v
```

Expected: all 11 PASS.

- [ ] **Step 5: Write the failing tests for invitations**

Create `tests/test_invitations.py`:

```python
from datetime import timedelta

import pytest

from app.core.businesstime import utcnow
from app.core.passwords import verify_password
from app.models.identity import UserAccount
from app.services.invitations import accept_invitation, create_invitation


def test_invitation_produces_a_token_and_row(db):
    token, invite = create_invitation(db, "new@example.com", "target_recorder", None)
    db.flush()
    assert token
    assert invite.token_hash != token
    assert invite.accepted_at is None


def test_invalid_role_is_refused(db):
    with pytest.raises(ValueError):
        create_invitation(db, "new@example.com", "wizard", None)


def test_accepting_creates_an_active_user_with_the_invited_role(db):
    token, _ = create_invitation(db, "sara@example.com", "target_recorder", None)
    db.flush()
    user = accept_invitation(db, token, "a-long-enough-password", "Sara")
    db.flush()
    assert isinstance(user, UserAccount)
    assert user.status == "active"
    assert verify_password("a-long-enough-password", user.password_hash)
    assert [row.role for row in user.roles] == ["target_recorder"]


def test_an_invitation_can_only_be_accepted_once(db):
    token, _ = create_invitation(db, "once@example.com", "target_recorder", None)
    db.flush()
    accept_invitation(db, token, "a-long-enough-password", "Once")
    db.flush()
    with pytest.raises(ValueError):
        accept_invitation(db, token, "another-long-password", "Again")


def test_expired_invitation_is_refused(db):
    token, invite = create_invitation(db, "old@example.com", "target_recorder", None)
    invite.expires_at = utcnow() - timedelta(minutes=1)
    db.flush()
    with pytest.raises(ValueError):
        accept_invitation(db, token, "a-long-enough-password", "Old")


def test_unknown_token_is_refused(db):
    with pytest.raises(ValueError):
        accept_invitation(db, "not-a-real-token", "a-long-enough-password", "Nobody")


def test_short_password_is_refused(db):
    token, _ = create_invitation(db, "short@example.com", "target_recorder", None)
    db.flush()
    with pytest.raises(ValueError):
        accept_invitation(db, token, "short", "Short")
```

- [ ] **Step 6: Run to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_invitations.py -v
```

Expected: FAIL — `app.services.invitations` does not exist.

- [ ] **Step 7: Write `app/services/invitations.py`**

```python
"""Staff invitations.

There is no public staff signup. An administrator invites a person and chooses
their role; the invitee sets their own password. Nobody ever sets or sees
another person's password.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.passwords import hash_password
from app.core.permissions import VALID_ROLES
from app.models.identity import Invitation, RoleAssignment, UserAccount

TOKEN_BYTES = 32
DEFAULT_VALID_HOURS = 72


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invitation(
    db: Session,
    email: str,
    role: str,
    invited_by: int | None,
    valid_hours: int = DEFAULT_VALID_HOURS,
) -> tuple[str, Invitation]:
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown role: {role}")
    token = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = Invitation(
        email=(email or "").strip().lower(),
        role=role,
        token_hash=_hash(token),
        expires_at=utcnow() + timedelta(hours=valid_hours),
        invited_by=invited_by,
    )
    db.add(invitation)
    return token, invitation


def accept_invitation(
    db: Session, token: str, password: str, display_name: str
) -> UserAccount:
    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == _hash(token or ""))
    )
    if invitation is None:
        raise ValueError("This invitation link is not valid")
    if invitation.accepted_at is not None:
        raise ValueError("This invitation has already been used")
    if invitation.expires_at <= utcnow():
        raise ValueError("This invitation has expired")

    user = UserAccount(
        email=invitation.email,
        password_hash=hash_password(password),  # raises on short passwords
        status="active",
        display_name=(display_name or "").strip() or None,
    )
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role=invitation.role))
    invitation.accepted_at = utcnow()
    return user
```

- [ ] **Step 8: Run to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_invitations.py -v
```

Expected: all 7 PASS.

- [ ] **Step 9: Commit**

```bash
git add app/services tests/test_auth_service.py tests/test_invitations.py
git commit -m "feat: session issuance, authentication, and staff invitations"
```

---

## Task 10: Auth API — bootstrap, login, logout, me, and permission dependencies

**Files:**
- Create: `hba-platform/app/api/deps.py`, `hba-platform/app/api/auth.py`
- Modify: `hba-platform/app/main.py`
- Test: `hba-platform/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `app.services.auth`, `app.services.invitations`, `app.services.audit`, `app.core.permissions`
- Produces: `current_user` dependency, `require_permission(permission)` dependency factory, routes `POST /api/auth/bootstrap`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app


# NOTE: TRUNCATE is impossible here and must not be attempted. audit_event
# refuses TRUNCATE, and truncating user_account cascades into it. Use the
# fresh_database fixture from conftest, which drops and re-migrates the schema.
@pytest.fixture(autouse=True)
def reset_identity(fresh_database):
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}


def test_bootstrap_creates_the_first_admin(client):
    response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    assert response.status_code == 201
    body = response.json()
    assert body["actor"]["role"] == "admin"
    assert "csrf" in body


def test_bootstrap_only_works_once(client):
    client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    second = client.post("/api/auth/bootstrap", json={**BOOTSTRAP, "email": "b@example.com"})
    assert second.status_code == 409


def test_login_succeeds_and_sets_a_session_cookie(client):
    client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]},
    )
    assert response.status_code == 200
    assert "hba_session" in response.cookies


def test_login_rejects_a_wrong_password(client):
    client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": "definitely-wrong-password"},
    )
    assert response.status_code == 401


def test_me_requires_a_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_actor_and_permissions(client):
    client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["actor"]["email"] == BOOTSTRAP["email"]
    assert "payroll.approve" in body["permissions"]


def test_logout_ends_the_session(client):
    boot = client.post("/api/auth/bootstrap", json=BOOTSTRAP).json()
    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": boot["csrf"]})
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_unsafe_request_without_csrf_is_rejected(client):
    client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    assert client.post("/api/auth/logout").status_code == 401


def test_bootstrap_is_recorded_in_the_audit_log(client):
    client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    with engine.connect() as connection:
        actions = [
            row[0] for row in connection.execute(text("SELECT action FROM audit_event"))
        ]
    assert "auth.bootstrap" in actions
```

- [ ] **Step 2: Run to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_auth_api.py -v
```

Expected: FAIL — the routes do not exist (404).

- [ ] **Step 3: Write `app/api/deps.py`**

```python
"""Request-scoped dependencies: who is calling, and may they do this?"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.permissions import has_permission, permissions_for
from app.db import get_session
from app.models.identity import RoleAssignment, UserAccount
from app.services.auth import resolve_session

SESSION_COOKIE = "hba_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def active_role(db: Session, user: UserAccount) -> str:
    row = (
        db.query(RoleAssignment)
        .filter(RoleAssignment.user_account_id == user.id, RoleAssignment.revoked_at.is_(None))
        .order_by(RoleAssignment.id.desc())
        .first()
    )
    return row.role if row else "affiliate"


def current_user(
    request: Request, db: Session = Depends(get_session)
) -> UserAccount:
    token = request.cookies.get(SESSION_COOKIE, "")
    csrf = None if request.method in SAFE_METHODS else request.headers.get("x-csrf-token")
    if request.method not in SAFE_METHODS and not csrf:
        raise HTTPException(401, "Authentication required")
    user = resolve_session(db, token, csrf)
    if user is None:
        raise HTTPException(401, "Authentication required")
    request.state.user = user
    return user


def require_permission(permission: str):
    """Build a dependency that enforces one permission, server-side."""

    def dependency(
        user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
    ) -> UserAccount:
        if not has_permission(active_role(db, user), permission):
            raise HTTPException(403, f"Permission required: {permission}")
        return user

    return dependency


def actor_payload(db: Session, user: UserAccount) -> dict:
    role = active_role(db, user)
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": role,
    }


def permission_list(db: Session, user: UserAccount) -> list[str]:
    return sorted(permissions_for(active_role(db, user)))
```

- [ ] **Step 4: Write `app/api/auth.py`**

```python
"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    SESSION_COOKIE,
    actor_payload,
    current_user,
    permission_list,
)
from app.config import settings
from app.core.passwords import hash_password
from app.db import get_session
from app.models.identity import RoleAssignment, UserAccount
from app.services.audit import record_audit
from app.services.auth import authenticate, issue_session, revoke_session

router = APIRouter(prefix="/api/auth")


class BootstrapBody(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


@router.post("/bootstrap", status_code=201)
def bootstrap(
    body: BootstrapBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """Create the very first administrator. Refused once any account exists."""
    if db.scalar(select(func.count()).select_from(UserAccount)):
        raise HTTPException(409, "An account already exists")

    user = UserAccount(
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        status="active",
        display_name=body.display_name.strip(),
    )
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role="admin"))

    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.bootstrap",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        after={"email": user.email, "role": "admin"},
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token)
    return {"actor": actor_payload(db, user), "csrf": csrf}


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    user = authenticate(db, str(body.email), body.password)
    if user is None:
        raise HTTPException(401, "Incorrect email or password")
    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.login",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token)
    return {"actor": actor_payload(db, user), "csrf": csrf}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    revoke_session(db, request.cookies.get(SESSION_COOKIE, ""))
    record_audit(
        db,
        action="auth.logout",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        ip_address=_client_ip(request),
    )
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"success": True}


@router.get("/me")
def me(
    user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
) -> dict:
    return {"actor": actor_payload(db, user), "permissions": permission_list(db, user)}
```

- [ ] **Step 5: Mount the router in `app/main.py`**

Replace the contents of `app/main.py` with:

```python
"""HBA Platform — FastAPI application entry point."""

from fastapi import FastAPI

from app.api import auth, health
from app.config import settings

app = FastAPI(
    title="HBA Platform",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.include_router(health.router)
app.include_router(auth.router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_auth_api.py -v
```

Expected: all 9 PASS.

- [ ] **Step 7: Run the whole suite**

```bash
./.venv/Scripts/python.exe -m pytest -v
```

Expected: every test passes. Record the total count in the commit message.

- [ ] **Step 8: Commit**

```bash
git add app tests
git commit -m "feat: auth API with server-side permission enforcement and CSRF"
```

---

## Task 11: React skeleton, single-service packaging, and Railway deployment

This task proves the deployment shape end to end before any real interface exists. Spec §19.

**Files:**
- Create: `hba-platform/frontend/` (Vite React app)
- Modify: `hba-platform/app/main.py`
- Create: `hba-platform/railway.json`, `hba-platform/nixpacks.toml`, `hba-platform/.railwayignore`
- Test: `hba-platform/tests/test_static_serving.py`

**Interfaces:**
- Consumes: `app.main:app`
- Produces: a deployed service answering `/api/health/ready`, serving the built bundle at `/`

- [ ] **Step 1: Create the React application**

```bash
cd "D:/Desktop/HBA/HBA Engineering/hba-platform"
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: Point the build output at `app/web` and proxy the API in development**

Replace `frontend/vite.config.ts` with:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../app/web",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
```

- [ ] **Step 3: Replace `frontend/src/App.tsx` with a minimal readiness page**

```tsx
import { useEffect, useState } from "react";

type Health = { status: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health/ready")
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => setError("Could not reach the API"));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "3rem" }}>
      <h1 style={{ fontWeight: 600 }}>HBA Platform</h1>
      <p style={{ color: "#666" }}>
        {error ?? (health ? `API status: ${health.status}` : "Checking API…")}
      </p>
    </main>
  );
}
```

- [ ] **Step 4: Build the bundle**

```bash
cd frontend
npm run build
cd ..
ls app/web/index.html
```

Expected: `app/web/index.html` exists.

- [ ] **Step 5: Write the failing test**

Create `tests/test_static_serving.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_serves_the_built_bundle():
    response = client.get("/")
    assert response.status_code == 200
    assert "HBA Platform" in response.text


def test_unknown_client_route_falls_back_to_the_bundle():
    # A single-page app owns its own routing; deep links must not 404.
    response = client.get("/affiliates/12")
    assert response.status_code == 200
    assert "<div id=\"root\">" in response.text


def test_unknown_api_route_still_returns_404():
    # The fallback must never swallow a genuine API mistake.
    assert client.get("/api/does-not-exist").status_code == 404
```

- [ ] **Step 6: Run to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_static_serving.py -v
```

Expected: FAIL — `/` returns 404.

- [ ] **Step 7: Serve the bundle from `app/main.py`**

Append to `app/main.py`:

```python
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).resolve().parent / "web"

if (WEB_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """Serve the single-page app for any non-API route.

        API routes are matched before this because they are registered first;
        an unmatched /api/* path therefore still returns a genuine 404.
        """
        if full_path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(404, "Not found")
        return FileResponse(WEB_DIR / "index.html")
```

- [ ] **Step 8: Run to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_static_serving.py -v
```

Expected: all 3 PASS.

- [ ] **Step 9: Write the Railway build and deploy configuration**

`nixpacks.toml`:

```toml
[phases.setup]
nixPkgs = ["python312", "nodejs_22"]

[phases.install]
cmds = [
  "python -m venv --copies /opt/venv && . /opt/venv/bin/activate && pip install -e .",
  "cd frontend && npm ci",
]

[phases.build]
cmds = ["cd frontend && npm run build"]

[start]
cmd = ". /opt/venv/bin/activate && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT"
```

`railway.json`:

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": { "builder": "NIXPACKS" },
  "deploy": {
    "healthcheckPath": "/api/health/ready",
    "healthcheckTimeout": 300,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 5
  }
}
```

`.railwayignore`:

```gitignore
.venv/
.git/
__pycache__/
tests/
docs/
frontend/node_modules/
*.log
.env
```

Migrations run at start, so a deploy that cannot migrate fails its health check rather than serving a half-migrated database.

- [ ] **Step 10: Run the whole suite one final time**

```bash
./.venv/Scripts/python.exe -m pytest -v
```

Expected: every test passes.

- [ ] **Step 11: Commit**

```bash
git add .
git commit -m "feat: React skeleton served by FastAPI, Railway deployment config"
```

- [ ] **Step 12: Deploy — requires explicit approval**

**Do not run this without the maintainer's go-ahead.** Creating a Railway service and provisioning a database are operational actions.

```bash
railway init            # create a NEW project; do not link to hba-affiliate
railway add             # attach PostgreSQL
railway up
```

Then set variables in Railway: `APP_ENV=production`, and confirm `DATABASE_URL` is provided by the attached database. Verify:

```bash
curl https://<new-domain>/api/health/ready
```

Expected: `{"status":"ready",...}` with `database.ok = true`.

---

## Definition of done for Phase 1

- [ ] `pytest` passes in full
- [ ] `alembic upgrade head` builds the schema from empty
- [ ] The database refuses UPDATE and DELETE on `audit_event`
- [ ] `target_recorder` provably cannot reach payroll or payment permissions
- [ ] Cairo month derivation is correct on both sides of a DST change
- [ ] Half-up rounding is proven distinct from Python's `round()`
- [ ] The deployed service answers `/api/health/ready` with `database.ok = true`
- [ ] Bootstrap creates exactly one admin and refuses a second

---

## Self-review

**Spec coverage.** §6.1 identity spine → Task 7. §6.2 authentication → Tasks 5, 9, 10. §6.3 code-defined permissions → Task 6. §5.1 roles including `target_recorder` → Task 6. §7 timezone → Task 4. §9.6 money and rounding → Task 3. §16 audit with masking → Task 8. §17 database invariants → Tasks 7 and 8 (role/status checks, append-only trigger); the remaining invariants concern tables built in later phases. §19 architecture and single-service deployment → Tasks 1, 2, 11.

**Deliberately deferred to later phases:** brute-force login throttling (Phase 3, alongside the affiliate login surface it protects), the notification outbox (Phase 2, with the Shopify work that needs it), and payout-destination security (Phase 8, when payout destinations exist).

**Type consistency.** `issue_session` returns `(token, csrf, row)` and is destructured that way in Tasks 9 and 10. `record_audit` is keyword-only after `db` and is called that way throughout. `has_permission(role, permission)` takes a role string, and `require_permission` resolves the role via `active_role` before calling it. `business_month` returns `"YYYY-MM"`, matching `parse_month`'s validation.

**Placeholder scan:** none. Every step contains the code or command it requires.
