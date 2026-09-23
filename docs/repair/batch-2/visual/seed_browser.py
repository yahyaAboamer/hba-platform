"""Fill a throwaway database with the approved export's own sample, so the two
can be put side by side and the difference is the *design*, not the data.

`scripts/seed_demo.py` makes five models, which is the right size for building a
screen and the wrong size for reviewing one: the roster's pager only appears
above twelve, *Content needing a look* wants a table with rows in it, and a
Payments desk with nothing settled shows one state out of four.

So this seeds the export's cast - the twenty-two people in `MODELS` at the
bottom of `Admin Dashboard.dc.html`, with their names, codes, arrangements and
requirement counts - and the situations the export's scenario buttons produce.

## The one thing that cannot match, stated plainly

**The export is set in November 2026 and the platform is running in September.**
`working_month()` reads the real clock in Africa/Cairo, and there is no honest
way to move it. Every join month is therefore shifted back two, so each model
stands in the same *relation* to the working month as her counterpart in the
export - ten months in is ten months in - but the month **labels** differ by
two, and a screenshot pair will read "September" against "November". That is
the difference to ignore while comparing; everything else is meant to line up.

## Destroys the database it points at

Same guard as `seed_demo.py` and one more: it refuses any database whose name
does not start with `hba_browser`, because this one is run by an agent against
whatever `DATABASE_URL` happens to be exported, and an environment variable is
exactly what went wrong on 10 September.

    DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_browser' \
    APP_ENV=development GO_LIVE_MONTH=2026-06 \
    .venv/Scripts/python.exe docs/repair/batch-2/visual/seed_browser.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.businesstime import month_add  # noqa: E402
from app.core.passwords import hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models.affiliates import AccountKind, AffiliateStatus  # noqa: E402
from app.models.attributed_orders import AttributedOrder, CommissionState  # noqa: E402
from app.models.catalogue import OrderLineItem, Product, ProductVariant  # noqa: E402
from app.models.compensation import CompensationType  # noqa: E402
from app.models.identity import UserAccount  # noqa: E402
from app.models.orders import OrderIndex  # noqa: E402
from app.services.affiliates import create_affiliate  # noqa: E402
from app.services.codes import register_code  # noqa: E402
from app.services.compensation import set_terms  # noqa: E402
from app.services.payments import record_payment  # noqa: E402
from app.services.payouts import set_destination  # noqa: E402
from app.services.payroll import approve_month, working_month  # noqa: E402
from app.services.shopify.fulfilment import DELIVERED, IN_FLIGHT  # noqa: E402
from app.services.targets import (  # noqa: E402
    get_target,
    record_actuals,
    record_outcome,
    set_requirements,
    verify,
)

PASSWORD = "a-long-enough-password"
OWNER_EMAIL = "owner@example.com"

#: The export's `SALARY` and `GUARANTEE`, in piastres.
SALARY = 1_200_000
GUARANTEE = 1_000_000

#: The export's cast, in its own order, with its own codes and requirements.
#: `joined` is the export's month **shifted back two** - see the module note.
COMMISSION, SALARY_PLUS, GUARANTEE_KIND = "commission", "salary", "guarantee"

MODELS = [
    # name, code, status, joined(export), terms, videos, stories
    ("Sara Edrees", "SARAED", "active", "2026-01",
     [("2026-01", COMMISSION, {}), ("2026-06", SALARY_PLUS, {"fixed": SALARY})], 6, 12),
    ("Malak Fahmy", "MALAK10", "active", "2026-01",
     [("2026-01", COMMISSION, {}), ("2026-07", COMMISSION, {"rate": 1500})], 6, 12),
    ("Hana Wagih", "HANAW", "active", "2026-02",
     [("2026-02", GUARANTEE_KIND, {"min": GUARANTEE, "rate": 1200})], 6, 12),
    ("Yahya Aboamer", "HBA15", "active", "2026-01",
     [("2026-01", COMMISSION, {}), ("2026-07", GUARANTEE_KIND, {"min": GUARANTEE})], 6, 12),
    ("Omar Sabry", "OMARS", "active", "2026-03", [("2026-03", COMMISSION, {})], 4, 8),
    ("Nadine Kamal", "NADK", "active", "2026-02",
     [("2026-02", SALARY_PLUS, {"fixed": 900_000})], 6, 12),
    ("Farida Zaki", "FARIDA", "active", "2026-04", [("2026-04", COMMISSION, {})], 4, 8),
    ("Youssef Adel", "YADEL", "active", "2026-05",
     [("2026-05", GUARANTEE_KIND, {"min": 150_000})], 4, 8),
    ("Laila Mostafa", "LAILAM", "active", "2026-03", [("2026-03", COMMISSION, {})], 6, 12),
    # Aya has no terms at all - the export's blocked row, and ours.
    ("Aya Sherif", "AYASH", "active", "2026-01", [], 4, 8),
    ("Dina Rashad", "DINAR", "active", "2026-07",
     [("2026-07", SALARY_PLUS, {"fixed": 800_000})], 6, 12),
    ("Jana Selim", "JANAS", "active", "2026-08", [("2026-08", COMMISSION, {})], 4, 8),
    ("Mariam Adel", "MARIAMA", "active", "2026-05",
     [("2026-05", GUARANTEE_KIND, {"min": GUARANTEE})], 6, 12),
    ("Rana Fouad", "RANAF", "active", "2026-09", [("2026-09", COMMISSION, {})], 4, 8),
    ("Salma Hegazy", "SALMAH", "active", "2026-04", [("2026-04", COMMISSION, {})], 6, 12),
    ("Tarek Aziz", "TAREKA", "active", "2026-06", [("2026-06", COMMISSION, {})], 4, 8),
    ("Yara Kassem", "YARAK", "active", "2026-10", [("2026-10", COMMISSION, {})], 4, 8),
    ("Ziad Nabil", "ZIADN", "active", "2026-07", [("2026-07", COMMISSION, {})], 4, 8),
    ("Zeina Hamdy", "ZEINAH", "active", "2026-11", [("2026-11", COMMISSION, {})], 4, 8),
    ("Nour Eldin", "NOURE", "inactive", "2026-01", [("2026-01", COMMISSION, {})], 4, 8),
    ("Habiba Sami", "HABIBAS", "application", "2026-11", [], 4, 8),
    ("Karim Diab", "KARIMD", "application", "2026-11", [], 4, 8),
]

#: The export's own product names, for Products and the best-seller lists.
PRODUCTS = [
    ("Oversized Wash Hoodie", "hoodie-wash", 185_000),
    ("Cargo Tailored Trouser", "cargo-trouser", 240_000),
    ("Ribbed Knit Top", "ribbed-knit", 95_000),
    ("Panel Track Jacket", "track-jacket", 320_000),
    ("Heavy Cotton Tee", "heavy-tee", 62_000),
    ("Wide Leg Denim", "wide-denim", 275_000),
    ("Logo Cap", "logo-cap", 45_000),
    ("Crossbody Nylon Bag", "nylon-bag", 130_000),
]


def _shift(month: str) -> str:
    """The export's month, moved back two so it lands the same distance from
    the working month as it does from the export's November."""
    return month_add(month, -2)


def refuse_anything_but_a_scratch_database() -> None:
    name = engine.url.database or ""
    if not name.startswith("hba_browser"):
        raise SystemExit(
            f"Refusing to run against {name!r}. This script empties every "
            "table. Point DATABASE_URL at a database named hba_browser*."
        )
    if settings.app_env != "development":
        raise SystemExit(f"Refusing to run: APP_ENV is {settings.app_env!r}.")


def empty_everything() -> None:
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


def account(db, name: str, email: str) -> int:
    row = UserAccount(
        email=email,
        password_hash=hash_password(PASSWORD),
        status="active",
        display_name=name,
    )
    db.add(row)
    db.flush()
    return row.id


_seq = [0]


def order(db, affiliate, code: str, month: str, piastres: int, *, state: str,
          products: list[tuple[str, str, int]]) -> str:
    """One order, attributed, with line items so the wardrobe and the
    best-seller lists have something real to read."""
    _seq[0] += 1
    key = f"o{_seq[0]:05d}"
    delivered = state == CommissionState.EARNED
    placed = datetime.fromisoformat(f"{month}-08T12:00:00+00:00")
    db.add(
        OrderIndex(
            shopify_order_id=key,
            order_number=f"#{1000 + _seq[0]}",
            placed_at=placed,
            business_month=month,
            discount_codes=[code],
            subtotal_piastres=piastres,
            total_piastres=piastres,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
            delivery_state=DELIVERED if delivered else IN_FLIGHT,
            delivery_status="DELIVERED" if delivered else "IN_TRANSIT",
            delivered_at=placed + timedelta(days=3) if delivered else None,
        )
    )
    db.flush()
    db.add(
        AttributedOrder(
            shopify_order_id=key,
            affiliate_id=affiliate.id,
            business_month=month,
            commission_base_piastres=piastres,
            commission_state=state,
            delivered_at=placed + timedelta(days=3) if delivered else None,
        )
    )
    share = max(piastres // max(len(products), 1), 100)
    for index, (title, handle, _price) in enumerate(products):
        db.add(
            OrderLineItem(
                shopify_line_item_id=f"{key}-{index}",
                shopify_order_id=key,
                shopify_product_id=handle,
                shopify_variant_id=f"{handle}-m",
                title=title,
                variant_title="M",
                sku=f"{handle.upper()}-M",
                quantity=1,
                discounted_total_piastres=share,
                original_total_piastres=share + 5_000,
            )
        )
    db.flush()
    return key


def main() -> None:
    refuse_anything_but_a_scratch_database()
    empty_everything()
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    working = working_month()

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

    for title, handle, price in PRODUCTS:
        db.add(
            Product(
                shopify_product_id=handle,
                shopify_product_gid=f"gid://shopify/Product/{handle}",
                title=title,
                handle=handle,
                status="active",
                image_url=None,
                updated_at_shopify=now,
            )
        )
        for position, size in enumerate(["S", "M", "L"]):
            db.add(
                ProductVariant(
                    shopify_variant_id=f"{handle}-{size.lower()}",
                    shopify_product_id=handle,
                    title=size,
                    sku=f"{handle.upper()}-{size}",
                    position=position,
                )
            )
    db.flush()

    made: dict[str, object] = {}
    for index, (name, code, status, joined, terms, videos, stories) in enumerate(MODELS):
        first = _shift(joined)
        email = name.split(" ")[0].lower() + "@example.com"
        affiliate = create_affiliate(
            db,
            user_account_id=account(db, name, email),
            name=name,
            phone=f"010 {1000 + index * 37:04d} {2000 + index * 53:04d}",
        )
        made[code] = affiliate
        if status == "application":
            continue
        affiliate.status = (
            AffiliateStatus.ACTIVE if status == "active" else AffiliateStatus.INACTIVE
        )
        affiliate.collaboration_start_month = first

        for start, kind, extra in terms:
            start = _shift(start)
            if kind == COMMISSION:
                set_terms(
                    db, affiliate, start_month=start,
                    compensation_type=CompensationType.COMMISSION,
                    commission_rate_bp=extra.get("rate", 1000),
                    expected_customer_discount_bp=1000,
                )
            elif kind == SALARY_PLUS:
                set_terms(
                    db, affiliate, start_month=start,
                    compensation_type=CompensationType.FIXED_PLUS_COMMISSION,
                    commission_rate_bp=extra.get("rate", 1000),
                    fixed_amount_piastres=extra["fixed"],
                    expected_customer_discount_bp=1000,
                )
            else:
                set_terms(
                    db, affiliate, start_month=start,
                    compensation_type=CompensationType.BASE_GUARANTEE,
                    commission_rate_bp=extra.get("rate", 1000),
                    base_amount_piastres=extra["min"],
                    expected_customer_discount_bp=1000,
                )

        register_code(db, affiliate, code, first, verified_at=now)

        if code in {"SARAED", "MALAK10", "HANAW", "HBA15"}:
            set_destination(
                db, affiliate, method="instapay",
                instapay_address_url=f"https://ipn.eg/{code.lower()}-2291",
                instapay_phone=f"010 {1000 + index * 37:04d} {2000 + index * 53:04d}",
            )

        # Orders across her whole run, so the year chart and *Sales generated*
        # have a shape rather than a single bar.
        month = first
        step = 0
        while month <= working:
            step += 1
            if code != "RANAF":  # the export's "new model, no sales"
                size = 400_000 + (index * 37_000 + step * 61_000) % 1_900_000
                order(db, affiliate, code, month, size,
                      state=CommissionState.EARNED,
                      products=PRODUCTS[(index + step) % 5:(index + step) % 5 + 2])
                if step % 3 == 0:
                    order(db, affiliate, code, month, size // 3,
                          state=CommissionState.PENDING,
                          products=PRODUCTS[(index + step) % 6:(index + step) % 6 + 1])
            # Targets: a requirement every live month, an outcome before go-live.
            from app.services.payroll import is_historical

            if is_historical(month):
                if any(k == GUARANTEE_KIND for _s, k, _e in terms):
                    record_outcome(db, affiliate, month, outcome="met")
            else:
                set_requirements(db, affiliate, month, videos=videos, stories=stories)
                if code != "MARIAMA":  # one guarantee left unrecorded, as the export has
                    target = get_target(db, affiliate, month)
                    record_actuals(
                        db, target,
                        videos=videos if index % 4 else max(videos - 2, 0),
                        stories=stories,
                        recorded_at=now,
                    )
                    if index % 3 != 2:
                        verify(db, target, actor_id=owner.id,
                               actor_email=OWNER_EMAIL, verified_at=now)
            month = month_add(month, 1)

    db.commit()

    # ── A settled month, a partly-paid month and an untouched one ────────────
    previous = month_add(working, -1)
    settled = []
    for code in ("SARAED", "MALAK10", "HANAW", "HBA15", "OMARS", "NADK"):
        affiliate = made[code]
        try:
            snapshot = approve_month(
                db, affiliate, previous, actor_id=owner.id, actor_email=OWNER_EMAIL
            )
        except ValueError as refusal:
            print(f"  {code} {previous}: {refusal}")
            continue
        settled.append((affiliate, snapshot))
    db.commit()

    for affiliate, snapshot in settled[:3]:
        owed = snapshot.approved_obligation_piastres
        # One paid in full, one short, one over - the three states the desk has.
        amount = {0: owed, 1: owed // 2, 2: owed}[settled.index((affiliate, snapshot))]
        if amount <= 0:
            continue
        record_payment(
            db, affiliate,
            amount_piastres=amount,
            allocations={snapshot.id: amount},
            occurred_at=now,
            reference=f"INSTA-{affiliate.id:04d}",
            note="Sent from the HBA account.",
            actor_id=owner.id,
            actor_email=OWNER_EMAIL,
        )
    db.commit()
    db.close()

    print(f"Seeded. Working month {working}, go-live {settings.go_live_month}.")
    print(f"Sign in as {OWNER_EMAIL} / {PASSWORD}")


if __name__ == "__main__":
    main()
