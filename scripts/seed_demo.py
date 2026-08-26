"""Fill a development database with a month that looks like a real one.

**Destroys everything in the database it points at.** It refuses to run unless
`APP_ENV` is `development`, because the one thing worse than no seed data is a
seed script that clears production while somebody is testing a screen.

Run it when you are building screens:

    python scripts/seed_demo.py

The test suite empties the database between tests, so anything seeded here is
gone the next time `pytest` runs. That is the tests behaving correctly - just
run this again afterwards.

## What it makes, and why these five

Five models, chosen so every state a payroll screen has to render is on the
page at once. A screen that only ever sees the happy row is a screen nobody has
really looked at.

    Nour     commission, code registered, money owed, one order still travelling
    Layla    salary plus commission - the arrangement with two figures in it
    Sara     guaranteed minimum, targets set but not recorded  -> blocked
    Malak    guaranteed minimum, nothing recorded at all       -> blocked
    Habiba   applied, no pay terms yet                         -> blocked
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.passwords import hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models.affiliates import AccountKind, AffiliateStatus  # noqa: E402
from app.models.attributed_orders import AttributedOrder, CommissionState  # noqa: E402
from app.models.compensation import CompensationType  # noqa: E402
from app.models.identity import UserAccount  # noqa: E402
from app.models.orders import OrderIndex  # noqa: E402
from app.services.affiliates import create_affiliate  # noqa: E402
from app.services.codes import register_code  # noqa: E402
from app.services.compensation import set_terms  # noqa: E402
from app.services.payouts import set_destination  # noqa: E402
from app.services.shopify.fulfilment import DELIVERED, IN_FLIGHT  # noqa: E402
from app.services.targets import set_requirements  # noqa: E402

MONTH = "2026-09"
PASSWORD = "a-long-enough-password"
OWNER_EMAIL = "owner@example.com"


def empty_everything() -> None:
    """Clear every table, keeping the schema.

    `session_replication_role` turns the append-only guards off for one
    transaction - the same trick the test suite uses. `SET LOCAL`, so it reverts
    on commit rather than riding along on a pooled connection.
    """
    with engine.begin() as connection:
        tables = list(
            connection.scalars(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
        )
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "TRUNCATE "
                + ", ".join(f'"{name}"' for name in tables)
                + " RESTART IDENTITY CASCADE"
            )
        )


def account(db, name: str) -> int:
    row = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password(PASSWORD),
        status="active",
        display_name=name,
    )
    db.add(row)
    db.flush()
    return row.id


def order(db, affiliate, key: str, code: str, piastres: int, *, state: str) -> None:
    """One order, attributed. `delivered` follows the state: an order that
    counts is one that arrived, and nothing else in the system disagrees."""
    delivered = state == CommissionState.EARNED
    db.add(
        OrderIndex(
            shopify_order_id=key,
            order_number=f"#{key}",
            placed_at=datetime(2026, 9, 15, 12, tzinfo=timezone.utc),
            business_month=MONTH,
            discount_codes=[code],
            subtotal_piastres=piastres,
            total_piastres=piastres,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
            delivery_state=DELIVERED if delivered else IN_FLIGHT,
            delivery_status="DELIVERED" if delivered else "IN_TRANSIT",
            delivered_at=datetime(2026, 9, 18, tzinfo=timezone.utc) if delivered else None,
        )
    )
    db.flush()
    db.add(
        AttributedOrder(
            shopify_order_id=key,
            affiliate_id=affiliate.id,
            business_month=MONTH,
            commission_base_piastres=piastres,
            commission_state=state,
            delivered_at=datetime(2026, 9, 18, tzinfo=timezone.utc) if delivered else None,
        )
    )
    db.flush()


def main() -> None:
    if settings.app_env != "development":
        raise SystemExit(
            f"Refusing to run: APP_ENV is {settings.app_env!r}. This script "
            "destroys every row in the database it points at."
        )

    empty_everything()
    db = SessionLocal()

    owner = UserAccount(
        email=OWNER_EMAIL,
        password_hash=hash_password(PASSWORD),
        status="active",
        display_name="Yahya",
    )
    db.add(owner)
    db.flush()
    db.execute(
        text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, 'admin')"),
        {"u": owner.id},
    )

    # ── Nour: everything in order, and one order still on its way ────────────
    nour = create_affiliate(
        db, user_account_id=account(db, "Nour"), name="Nour", phone="010 1234 5678"
    )
    nour.status = AffiliateStatus.ACTIVE
    set_terms(
        db, nour, start_month="2026-01",
        compensation_type=CompensationType.COMMISSION, commission_rate_bp=1000,
        expected_customer_discount_bp=1000,
    )
    register_code(db, nour, "NOUR10", "2026-01", verified_at=datetime.now(timezone.utc))
    set_destination(
        db, nour, method="instapay",
        instapay_address_url="https://ipn.eg/nour-abdelrahman-2291",
        instapay_phone="010 1234 5678",
    )
    order(db, nour, "n-1", "NOUR10", 2_400_000, state=CommissionState.EARNED)
    order(db, nour, "n-2", "NOUR10", 480_000, state=CommissionState.PENDING)

    # ── Layla: salary plus commission ────────────────────────────────────────
    layla = create_affiliate(db, user_account_id=account(db, "Layla"), name="Layla")
    layla.status = AffiliateStatus.ACTIVE
    set_terms(
        db, layla, start_month="2026-01",
        compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
        commission_rate_bp=800, fixed_amount_piastres=500_000,
    )
    register_code(db, layla, "LAYLA10", "2026-01", verified_at=datetime.now(timezone.utc))
    order(db, layla, "l-1", "LAYLA10", 640_000, state=CommissionState.EARNED)

    # ── Sara: guaranteed minimum, targets set and not yet recorded ───────────
    sara = create_affiliate(db, user_account_id=account(db, "Sara"), name="Sara")
    sara.status = AffiliateStatus.ACTIVE
    set_terms(
        db, sara, start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000, base_amount_piastres=800_000,
    )
    register_code(db, sara, "SARA10", "2026-01", verified_at=datetime.now(timezone.utc))
    set_requirements(db, sara, MONTH, videos=8, stories=5)
    order(db, sara, "s-1", "SARA10", 1_100_000, state=CommissionState.EARNED)

    # ── Malak: guaranteed minimum, nothing recorded at all ───────────────────
    malak = create_affiliate(db, user_account_id=account(db, "Malak"), name="Malak")
    malak.status = AffiliateStatus.ACTIVE
    set_terms(
        db, malak, start_month="2026-01",
        compensation_type=CompensationType.BASE_GUARANTEE,
        commission_rate_bp=1000, base_amount_piastres=600_000,
    )
    register_code(db, malak, "MALAK10", "2026-01")
    order(db, malak, "m-1", "MALAK10", 210_000, state=CommissionState.EARNED)

    # ── Habiba: applied, nothing set up yet ──────────────────────────────────
    habiba = create_affiliate(db, user_account_id=account(db, "Habiba"), name="Habiba")
    order(db, habiba, "h-1", "HABIBA10", 380_000, state=CommissionState.EARNED)

    # ── HBA's own code: real sales, never owed anything ──────────────────────
    house = create_affiliate(
        db, user_account_id=account(db, "House"), name="HBA house code",
        account_kind=AccountKind.HOUSE,
    )
    house.status = AffiliateStatus.ACTIVE
    register_code(db, house, "HBA10", "2026-01", verified_at=datetime.now(timezone.utc))
    order(db, house, "hb-1", "HBA10", 3_100_000, state=CommissionState.EARNED)

    db.commit()
    db.close()

    print(f"Seeded {MONTH}. Sign in as {OWNER_EMAIL} / {PASSWORD}")
    print("Set GO_LIVE_MONTH=2026-09 so the month is live rather than historical.")


if __name__ == "__main__":
    main()
