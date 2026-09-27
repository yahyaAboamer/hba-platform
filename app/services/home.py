"""Her Home, in one read.

Home used to make three requests - the month, the payments, the year - and
drew each part as it arrived, so the chart appeared a moment after everything
else and pushed the page about. This gathers them, and the few figures Home
gained in batch L, into one answer.

**Nothing here is a second way of working anything out.** The month is
`my_month`, the payments `my_payments`, the year `my_year`, the rank
`month_performance`, the targets `my_targets` - the same functions their own
screens read. The only new arithmetic is the like-for-like comparison, and it
sums the same column the month's sales figure sums, over a shorter window.
"""

from calendar import monthrange
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import BUSINESS_TIMEZONE, business_date, month_add, utcnow
from app.core.money import format_egp
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.integration import ShopifyConnection
from app.models.orders import OrderIndex
from app.services.commission.calculate import COUNTED_STATES
from app.services.commission.state import order_status

_SHORT = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _end_of_day(day: date) -> datetime:
    """The first instant after `day` in Cairo - the cut-off for "placed on or
    before this day". Business days are Cairo days (`app/core/businesstime.py`),
    so a UTC midnight would move orders placed after 10pm Cairo time into the
    wrong day. Timezone-aware, so the database compares it correctly with the
    UTC `placed_at`."""
    return datetime.combine(day + timedelta(days=1), time.min, BUSINESS_TIMEZONE)


def sales_through(
    db: Session, affiliate_id: int, month: str, through: date | None
) -> int:
    """Her counted sales for `month`, from its first day to `through`.

    **The same figure Home calls sales**: `commission_base_piastres` over the
    counted states (delivered and pending, never a failed delivery - F02,
    ADR 0040), for her orders in that business month. With `through` absent
    it is the whole month, and equals `sales.counted_piastres` exactly;
    `tests/test_home.py` holds the two together.
    """
    query = (
        select(func.coalesce(func.sum(AttributedOrder.commission_base_piastres), 0))
        .select_from(AttributedOrder)
        .where(AttributedOrder.affiliate_id == affiliate_id)
        .where(AttributedOrder.business_month == month)
        .where(AttributedOrder.commission_state.in_(COUNTED_STATES))
    )
    if through is not None:
        query = query.join(
            OrderIndex, OrderIndex.shopify_order_id == AttributedOrder.shopify_order_id
        ).where(OrderIndex.placed_at < _end_of_day(through))
    return int(db.scalar(query) or 0)


def comparison(
    db: Session, affiliate_id: int, month: str, today: date
) -> dict | None:
    """This month's sales against last month's, **like for like**.

    The owner's rule, 27 September: a month still running is compared with
    the *same days* of the one before - the 1st to the 10th against the 1st
    to the 10th - because a finished month will always look bigger than one
    ten days old. A finished month is compared whole with the month before.

    - The day is Cairo's today. A previous month shorter than today's date
      stops at its own last day (the 31st against a 30-day month is its 30th).
    - `None` when last month sold nothing in that window: a percentage of
      nothing is not a number, and "new" would be a claim about her.
    - The percentage is worked out here and sent whole, because nothing about
      money is calculated in the browser (docs/RULES.md).
    """
    previous = month_add(month, -1)
    year, number = (int(part) for part in previous.split("-"))
    running = today.strftime("%Y-%m") == month
    if running:
        cutoff = date(year, number, min(today.day, monthrange(year, number)[1]))
        now = sales_through(db, affiliate_id, month, today)
        before = sales_through(db, affiliate_id, previous, cutoff)
        window = f"1–{cutoff.day} {_SHORT[number]}"
    else:
        now = sales_through(db, affiliate_id, month, None)
        before = sales_through(db, affiliate_id, previous, None)
        window = f"all of {_SHORT[number]}"
    if before <= 0:
        return None
    return {
        "previous_month": previous,
        "window": window,
        "running": running,
        "now_piastres": now,
        "now": format_egp(now),
        "before_piastres": before,
        "before": format_egp(before),
        "change_pct": int(round((now - before) * 100 / before)),
    }


def order_outcomes(db: Session, affiliate_id: int, month: str) -> dict:
    """How many of her orders in the month ended each way - **every way**.

    The owner found 16 code uses beside 10 delivered, 3 pending and 0 failed
    (FITBROS10, September 2026): three orders were cancelled before delivery.
    Every order is a use (ADR 0049), so all five outcomes add up to the uses;
    Home shows them as three - *failed* holding failed deliveries,
    cancellations and refunds (ADR 0048, amended). Counted by `order_status`,
    the same decision each order's own row shows.
    """
    rows = db.execute(
        select(AttributedOrder, OrderIndex)
        .join(
            OrderIndex,
            OrderIndex.shopify_order_id == AttributedOrder.shopify_order_id,
            isouter=True,
        )
        .where(AttributedOrder.affiliate_id == affiliate_id)
        .where(AttributedOrder.business_month == month)
    ).all()
    outcomes = {"delivered": 0, "pending": 0, "failed": 0, "cancelled": 0, "refunded": 0}
    for order, index in rows:
        status = order_status(
            state=order.commission_state,
            delivery_state=index.delivery_state if index else None,
            cancelled_at=index.cancelled_at if index else None,
            financial_status=index.financial_status if index else None,
        )
        outcomes[status] = outcomes.get(status, 0) + 1
    return outcomes


def share_link(db: Session, code: str | None) -> str | None:
    """A shop link that applies her code at checkout.

    Shopify's own discount link, `https://<shop>/discount/<CODE>`: opening it
    stores the code for the visit, and the shop redirects to its storefront.
    The domain is the saved connection's, else the environment's - read
    directly, because building a link must never decrypt a credential.
    """
    from app.config import settings

    if not code:
        return None
    saved = db.get(ShopifyConnection, 1)
    domain = (saved.shop_domain if saved else "") or settings.shopify_shop_domain
    domain = (domain or "").strip().removeprefix("https://").removeprefix("http://").strip("/")
    if not domain:
        return None
    return f"https://{domain}/discount/{code}"


def home(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """Everything Home draws for one month, in one answer."""
    from app.services.codes import codes_with_status
    from app.services.performance import best_sellers_for, month_performance
    from app.services.portal import my_month, my_payments, my_targets, my_year

    today = business_date(utcnow())

    board = month_performance(db, month)
    mine = next((row for row in board if row.affiliate_id == affiliate.id), None)

    target = next(
        (row for row in my_targets(db, affiliate)["months"] if row.get("month") == month),
        None,
    )

    best = best_sellers_for(db, affiliate.id, month=month)

    codes = codes_with_status(db, affiliate, month)
    verified = next((entry["code"] for entry in codes if entry.get("verified")), None)

    return {
        "month": month,
        "earnings": my_month(db, affiliate, month),
        "outcomes": order_outcomes(db, affiliate.id, month),
        "payments": my_payments(db, affiliate),
        "year": my_year(db, affiliate),
        "rank": {"rank": mine.rank, "of": len(board)} if mine else None,
        "content": (
            {
                key: target.get(key)
                for key in (
                    "required_videos",
                    "actual_videos",
                    "required_stories",
                    "actual_stories",
                    "verified",
                )
            }
            if target
            and (target.get("required_videos") or target.get("required_stories"))
            else None
        ),
        "best_seller": (
            {
                "title": best[0].title,
                "quantity": best[0].quantity,
                "sales_piastres": best[0].sales_piastres,
                "sales": format_egp(best[0].sales_piastres),
            }
            if best
            else None
        ),
        "comparison": comparison(db, affiliate.id, month, today),
        # Only a code HBA has checked is worth sharing: a pending one may yet
        # be refused, and customers would be sent a code that does nothing.
        "share": (
            {"code": verified, "url": share_link(db, verified)} if verified else None
        ),
    }
