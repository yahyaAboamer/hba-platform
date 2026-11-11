"""The Targets states `seed_browser.py` does not reach, added on top of it.

Run after `seed_browser.py`, against the same throwaway database. Every figure
is still computed by the platform's own services; this only chooses which
records exist. Seeded people carry *(test)* where they are new.

States added, all in the working month unless named:

- **On pace, target missed** (Laila, last month): more videos than asked, fewer
  stories, the two together reach the line. The weekly pace adds videos and
  stories; the target needs each.
- **Recorded zero** (Salma).
- **Recorded before this week began** (Tarek): the pace says nobody typed.
- **Nothing asked for** (Ziad, commission) and **a guarantee with nothing
  asked for** (Youssef): no target row at all.
- **Before her start** with a long name (new, starts next month).

    DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_browser_targets' \
    APP_ENV=development GO_LIVE_MONTH=2026-06 \
    .venv/Scripts/python.exe docs/repair/batch-2/visual/seed_targets.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from sqlalchemy import select  # noqa: E402

from app.core.businesstime import month_add  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.modules.affiliates.models.affiliates import AffiliateProfile, AffiliateStatus  # noqa: E402
from app.modules.affiliates.models.compensation import CompensationType  # noqa: E402
from app.modules.affiliates.models.targets import MonthlyTarget  # noqa: E402
from app.modules.affiliates.services.affiliates import create_affiliate  # noqa: E402
from app.modules.affiliates.services.compensation import set_terms  # noqa: E402
from app.modules.affiliates.services.payroll import working_month  # noqa: E402
from app.modules.affiliates.services.targets import (  # noqa: E402
    get_target,
    record_actuals,
)
from app.shared.models.identity import UserAccount  # noqa: E402
from app.core.passwords import hash_password  # noqa: E402


def by_name(db, name: str) -> AffiliateProfile:
    return db.scalar(select(AffiliateProfile).where(AffiliateProfile.name == name))


def main() -> None:
    if not (engine.url.database or "").startswith("hba_browser"):
        raise SystemExit("Refusing: only an hba_browser* scratch database.")
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    working = working_month()
    previous = month_add(working, -1)

    # On pace, target missed - in a finished month, where it is starkest.
    laila = by_name(db, "Laila Mostafa")
    target = get_target(db, laila, previous)
    record_actuals(db, target, videos=8, stories=10, recorded_at=now)

    # Recorded zero.
    salma = by_name(db, "Salma Hegazy")
    target = get_target(db, salma, working)
    record_actuals(db, target, videos=0, stories=0, recorded_at=now)

    # Recorded before this week began.
    tarek = by_name(db, "Tarek Aziz")
    target = get_target(db, tarek, working)
    target.recorded_at = now - timedelta(days=12)

    # Nothing asked for: no target row at all.
    for name in ("Ziad Nabil", "Youssef Adel"):
        found = get_target(db, by_name(db, name), working)
        if found is not None:
            db.delete(found)

    # Before her start, with a name long enough to wrap.
    user = UserAccount(
        email="mariam.long@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name="Mariam",
    )
    db.add(user)
    db.flush()
    late = create_affiliate(
        db,
        user_account_id=user.id,
        name="Mariam Abdelrahman El-Sayed Mostafa (test)",
        phone="010 5555 1212",
    )
    late.status = AffiliateStatus.ACTIVE
    late.collaboration_start_month = month_add(working, 1)
    set_terms(
        db, late, start_month=month_add(working, 1),
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
        expected_customer_discount_bp=1000,
    )

    db.commit()
    rows = db.scalars(select(MonthlyTarget).where(MonthlyTarget.month == working)).all()
    print(f"Targets states added. {working}: {len(rows)} target rows.")
    db.close()


if __name__ == "__main__":
    main()
