"""What a model may do to their own record.

Gated on `current_affiliate` - ownership, never a permission (§6.1). Every
route here acts on the caller's own profile and takes no affiliate id at all,
so there is no parameter to tamper with: reaching another model's record is
not refused, it is unexpressible.

§6.5 bounds what appears here. They may correct how to reach them and where their
money goes. They may not touch a rate, a target, an order, or a month state.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_affiliate, current_user
from app.core.money import format_egp
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.identity import UserAccount
from app.models.payments import PaymentTransaction
from app.services.affiliates import (
    SHIPPING_FIELDS,
    update_measurements,
    update_shipping_address,
)
from app.services.applications import REQUIRED_PAYOUT_FIELDS, application_state
from app.services.auth import authenticate
from app.services.codes import codes_with_status
from app.services.notification_prefs import preferences_for, set_preference
from app.services.payouts import (
    reveal_destination,
    changed_recently,
    current_destination,
    mask_destination,
    set_destination,
)
from app.services.policy import get_policy_version
from app.services.portal import (
    months_for,
    my_month,
    my_orders,
    my_payments,
    my_targets,
    my_year,
)
from app.services.proof import readable_by

router = APIRouter(prefix="/api/me")


class PayoutChangeBody(BaseModel):
    #: §6.4.1. Not the session - a session is what an attacker already has.
    password: str = Field(min_length=1, max_length=256)
    method: str

    instapay_address_url: str | None = Field(default=None, max_length=500)
    instapay_phone: str | None = Field(default=None, max_length=40)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_holder: str | None = Field(default=None, max_length=120)
    bank_account_number: str | None = Field(default=None, max_length=60)
    wallet_provider: str | None = Field(default=None, max_length=60)
    wallet_phone: str | None = Field(default=None, max_length=40)


@router.get("")
def me(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Their own record, as they are allowed to see it.

    The payout destination is **masked even to them**. They supplied it, so it
    tells them nothing they do not know - and a screen that prints a full
    account number is a screen worth photographing over somebody's shoulder.
    Recognising which account is theirs is all this has to do.
    """
    destination = current_destination(db, affiliate)
    return {
        "name": affiliate.name,
        "phone": affiliate.phone,
        #: **The one email she has** (D07, 9 September 2026). It is what she
        #: signs in with and where HBA writes to her, and there is no second
        #: contact address - so every screen that shows it says which it is,
        #: rather than "email", which invites somebody to treat a login as a
        #: contact detail.
        "email": affiliate.account.email,
        #: Hers to write (A05). Returned so her own screen can show and edit
        #: them; the maintainer's payload carries them read-only.
        "height_cm": affiliate.height_cm,
        "weight_kg": affiliate.weight_kg,
        #: D11. Hers, and staff write it too - they type it into the order.
        "shipping": {field: getattr(affiliate, field) for field in SHIPPING_FIELDS},
        "status": affiliate.status,
        "state": application_state(db, affiliate),
        #: Which of the three arrangements she is on **this month**, raw, with
        #: her own screen putting the words on it - as Targets and Payments do,
        #: so there is one vocabulary and not three.
        #:
        #: `None` where nobody has set terms for her yet, which is not the same
        #: as commission: one is an arrangement and the other is a gap, and a
        #: screen that showed the gap as commission would be quoting her a rate
        #: nobody agreed.
        "arrangement": _arrangement_now(db, affiliate),
        #: When she started with HBA, where somebody recorded it. `None` is
        #: ordinary - it is filled in for models brought over from before the
        #: platform, and the screen simply says less without it.
        "since": affiliate.collaboration_start_month,
        "codes": codes_with_status(db, affiliate, affiliate.created_at.strftime("%Y-%m"))
        if affiliate.created_at
        else [],
        "payout_destination": mask_destination(destination),
        "required_fields": {
            method: list(fields) for method, fields in REQUIRED_PAYOUT_FIELDS.items()
        },
    }


def _arrangement_now(db: Session, affiliate: AffiliateProfile) -> str | None:
    """Her compensation type in the working month, or `None` if none is set.

    Asked about a month rather than "current terms", because terms are dated
    (`terms_for`): a model can be on commission in one month and a guaranteed
    minimum in the next, and the working month is the one her screens are
    about.
    """
    from app.services.compensation import terms_for
    from app.services.portal import working_month

    terms = terms_for(db, affiliate, working_month())
    return terms.compensation_type if terms else None


class NotificationPreferenceBody(BaseModel):
    kind: str = Field(max_length=40)
    enabled: bool


@router.get("/notifications")
def my_notification_preferences(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Which of the two messages they want.

    Both on until they say otherwise - there is no row for the default, so a
    model who has never opened this screen hears about their month closing and
    about being paid.
    """
    return {"preferences": preferences_for(db, affiliate)}


@router.put("/notifications")
def change_my_notification_preferences(
    body: NotificationPreferenceBody,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Turn one switch on or off.

    **No password.** §6.4 asks for one where money moves; muting an email
    moves nothing, and asking for a password to change a notification setting
    teaches people to type it whenever a screen asks.

    One switch per request rather than the whole set, so two tabs open on this
    screen cannot write over each other's other switch.
    """
    try:
        set_preference(db, affiliate, kind=body.kind, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"preferences": preferences_for(db, affiliate)}


@router.get("/payout-destination")
def my_payout_destination_in_full(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """The same details, unmasked, for the person who typed them.

    **Masked at rest is right; masked with no way to look is not.** `/me`
    returns the destination masked, which is correct for a screen that sits
    open on a phone on a table. But the one person entitled to check the whole
    thing is the person whose account it is, and until now they could not - so
    somebody who mistyped a digit had no way to find out except by not being
    paid.

    Behind a deliberate press on their own screen, and **no password**. §6.4
    asks for the password to *change* where money goes, because that is the
    act an attacker with a stolen session wants. Reading back a number they
    typed themselves is not that act, and demanding a password to look at your
    own bank details teaches people to type passwords whenever a screen asks -
    which costs more security than it buys.

    Goes through the same `reveal_destination` the maintainer's payer uses, so
    there is one implementation and one audit trail. The audit row records
    that somebody looked and never what they saw - writing the value into the
    log would recreate exactly the leak masking exists to prevent.
    """
    try:
        return reveal_destination(
            db,
            affiliate,
            actor_id=user.id,
            actor_email=user.email,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/payout-destination")
def change_payout_destination(
    body: PayoutChangeBody,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """§6.4. Move where their money goes.

    The highest-risk thing a model can do: a compromised account that can
    silently repoint an InstaPay address can redirect an entire payout.

    **The password is re-entered, not the session.** A session is what an
    attacker has - a hijacked cookie, a borrowed phone. The password is what
    they may not, and this is the one action where that distinction is worth
    the friction.

    Checked with `authenticate`, the same function that checks it at sign-in,
    so the two can never disagree about what a correct password is.

    The response is **masked**, even though the caller just typed the raw
    value. Echoing it back is a second place it could be logged, and a
    response body gets captured by more things than a request body does.
    """
    if authenticate(db, user.email, body.password) is None:
        # Deliberately not "wrong password" versus "account problem": both
        # answers are the same to somebody who should not be here.
        raise HTTPException(403, "That password is not right")

    fields = {
        field: getattr(body, field)
        for field in REQUIRED_PAYOUT_FIELDS.get(body.method, ())
    }
    missing = [field for field, value in fields.items() if not str(value or "").strip()]
    if missing:
        raise HTTPException(
            400,
            "These are needed before we can pay you: "
            + ", ".join(field.replace("_", " ") for field in missing),
        )

    before = mask_destination(current_destination(db, affiliate))

    try:
        destination = set_destination(
            db,
            affiliate,
            method=body.method,
            actor_id=user.id,
            actor_email=user.email,
            **fields,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {
        # §6.4.2. Both sides, masked, so they can confirm what they changed
        # without the screen printing either in full.
        "before": before,
        "after": mask_destination(destination),
    }


@router.get("/payout-destination/changed-recently")
def destination_changed_recently(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """When their destination last moved, if it was lately.

    Theirs to see as well as the maintainer's. A model who did not make that
    change is the first person who would notice, and the only one who can say
    so.
    """
    changed = changed_recently(db, affiliate)
    return {"changed_at": changed.isoformat() if changed else None}


# -- What they have earned (Phase 9, §11.1 and §11.4) ---------------------------


def _month_or_400(month: str) -> str:
    from app.core.businesstime import parse_month

    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


@router.get("/months")
def my_months(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """The months they can look at, newest first.

    Theirs, not the calendar's. The maintainer's picker offers every month
    because they are choosing which payroll to run; a model offered a month from
    before they joined would find an empty screen and no way to tell whether
    that meant nothing happened or something broke.
    """
    months = months_for(db, affiliate)
    return {"months": months, "working_month": months[0] if months else None}


@router.get("/earnings/{month}")
def my_earnings(
    month: str,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """One of their months, and every order behind the figure.

    The orders travel with the month deliberately. The first thing anybody does
    with a payment figure is try to reconcile it against what they think they
    sold, and a screen that makes them ask for the detail separately is a screen
    that makes them ask HBA instead.

    Nothing here is recalculated for them: an agreed month is read out of its
    snapshot, an open one out of the same `calculate_month` the payroll screen
    uses. Two implementations of what they are owed would be two answers waiting
    to disagree, and they would be paid the other one.
    """
    month = _month_or_400(month)
    return {
        **my_month(db, affiliate, month),
        "orders_detail": my_orders(db, affiliate, month),
    }


@router.get("/payments")
def my_payment_history(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """What has arrived, and what is still outstanding.

    §14. A different route from their earnings on purpose, and it stays
    different: *what I have earned* and *what has arrived* have different
    answers for most of any month.

    Ownership again, and no affiliate id anywhere - the settlement figures come
    from the same `balance_for` the maintainer's payment screen uses, so the
    number they chase and the number they see cannot disagree.
    """
    return my_payments(db, affiliate)


@router.get("/payments/{payment_id}/proof")
def my_payment_proof(
    payment_id: int,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> Response:
    """The transfer screenshot for one of their payments.

    §14 and ADR 0017: proof is shown to the affiliate because visible proof
    removes an entire category of *"did you send it?"* messages. The business
    accepted the recorded risk that a screenshot may expose HBA's own banking
    details to about twenty people; the mitigations that made that acceptable -
    EXIF stripped, re-encoded, size-capped, and **served only to the owner** -
    are conditions, not extras.

    The last of those lives in `readable_by`, whose docstring has named this
    route since Phase 7: *"the affiliate's own route arrives in Phase 9 and
    calls the same `readable_by`, so the two cannot drift apart on the rule."*
    This is that route, and it calls it rather than re-checking the rule here.

    The ownership check on the transaction comes first all the same. Without
    it, asking for a payment id that is not theirs would be answered by whether
    the *file* was theirs - a slower path to the same 404, and one that reveals
    which payment ids exist by how long it takes.
    """
    transaction = db.get(PaymentTransaction, payment_id)
    if (
        transaction is None
        or transaction.affiliate_id != affiliate.id
        or transaction.proof_file_id is None
    ):
        raise HTTPException(404, "No proof for that payment")

    stored = readable_by(db, transaction.proof_file_id, affiliate_id=affiliate.id)
    if stored is None:
        raise HTTPException(404, "No proof for that payment")

    return Response(content=stored.content, media_type=stored.content_type)


@router.get("/year")
def my_year_view(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Every month they have, for the charts.

    Nothing here is new arithmetic - each month is the same figure the Earnings
    screen shows, gathered. A second way of working out what they earned would
    be a second answer waiting to disagree with the first.
    """
    return my_year(db, affiliate)


@router.get("/policy/{policy_version_id}")
def my_policy_version(
    policy_version_id: int,
    _affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """The rules a settled month names, in full.

    Not ownership-scoped like everything else here - a policy version is a
    platform-wide fact, the same text whoever reads it, not a record that
    belongs to one affiliate. `current_affiliate` still gates it: signed in
    as a model is what this route requires, not signed in as this model.
    """
    version = get_policy_version(db, policy_version_id)
    if version is None:
        raise HTTPException(404, "No such policy version")
    return {
        "id": version.id,
        "effective_month": version.effective_month,
        "summary_markdown": version.summary_markdown,
    }


class MeasurementsBody(BaseModel):
    """Her height and her weight, and nothing else.

    **No password.** §6.4.1 asks for one before a payout destination changes,
    because that is where money goes and a session is what an attacker already
    has. A height is not that: the worst an intruder does here is make HBA send
    the wrong size, and asking her for a password every time she corrects a
    number she volunteered would teach her to type it into anything that asked.

    Both nullable and both optional. `None` for a field means *leave it alone*;
    clearing one is done by sending it with `_set`, the same shape the
    maintainer's start-month field uses, and for the same reason - absence and
    "make it empty" cannot be the same request.
    """

    height_cm: int | None = Field(default=None, ge=100, le=250)
    height_cm_set: bool = False
    weight_kg: int | None = Field(default=None, ge=30, le=250)
    weight_kg_set: bool = False


@router.put("/measurements")
def update_my_measurements(
    body: MeasurementsBody,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Her measurements, written by her.

    **A05: she writes these and staff read them.** This is the only route into
    `update_measurements`, and its absence from the maintainer's API is the
    enforcement - not a permission check inside a function an admin route could
    still call. `test_affiliates_api.py` proves the staff PATCH ignores a
    `height_cm` rather than obeying it.

    Optional in both directions. She may give one and not the other, give
    neither, or take one back after giving it - and none of those is an error,
    because A05 makes them optional at every point in her life with the
    business rather than only on the day she applies.
    """
    try:
        update_measurements(
            db,
            affiliate,
            # `UNSET` where she said nothing, so the service can tell "leave it
            # alone" from "take it off my record" - and both are audited.
            **({"height_cm": body.height_cm} if body.height_cm_set else {}),
            **({"weight_kg": body.weight_kg} if body.weight_kg_set else {}),
            actor_id=affiliate.user_account_id,
            actor_email=affiliate.account.email,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"height_cm": affiliate.height_cm, "weight_kg": affiliate.weight_kg}


class ShippingBody(BaseModel):
    """Where HBA sends her things.

    **No password**, for the same reason measurements need none: this decides
    where a parcel goes, not where money goes. §6.4.1 reserves reauthentication
    for the payout destination, and asking for it on every ordinary edit is how
    somebody learns to type their password into anything that asks.

    Every field optional, and an empty string clears one - a second address
    line that no longer applies should be removable.
    """

    shipping_name: str | None = Field(default=None, max_length=200)
    shipping_phone: str | None = Field(default=None, max_length=40)
    shipping_line1: str | None = Field(default=None, max_length=300)
    shipping_line2: str | None = Field(default=None, max_length=300)
    shipping_city: str | None = Field(default=None, max_length=120)
    shipping_governorate: str | None = Field(default=None, max_length=120)
    shipping_notes: str | None = Field(default=None, max_length=500)


@router.put("/shipping-address")
def update_my_shipping_address(
    body: ShippingBody,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Her address, written by her.

    D11: **both sides edit this.** Unlike her measurements, which are hers
    alone, staff may write it too - they are the ones typing it into an order,
    and a model who has moved should not be a parcel that cannot be sent. The
    audit records which side made each change.

    Only the keys she actually sends are touched, so a form that edits one line
    cannot blank the rest.
    """
    supplied = body.model_dump(exclude_unset=True)
    try:
        update_shipping_address(
            db,
            affiliate,
            supplied,
            actor_id=affiliate.user_account_id,
            actor_email=affiliate.account.email,
            actor_is_staff=False,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        field: getattr(affiliate, field) for field in SHIPPING_FIELDS
    }


@router.get("/wardrobe")
def my_wardrobe(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """What HBA has sent her, and the requests she may actually see.

    **Only what HBA sent** (D05, 10 September 2026). Something she bought with
    her own money is not here — the wardrobe is a record of what the business
    gave her, not an inventory of her cupboard.

    The feature requests are the *intersection* of visible requests and what
    she holds, computed here (W10). Filtering in the browser would still hand
    every request to every model through this endpoint, which is the difference
    between hiding something and not sending it.
    """
    from app.services.wardrobe import eligible_requests, wardrobe_for

    wardrobe = wardrobe_for(db, affiliate.id)
    return {
        **wardrobe,
        # An empty list means the section disappears rather than rendering an
        # empty header (W11).
        "feature_requests": eligible_requests(db, affiliate.id),
    }


@router.get("/best-sellers")
def my_best_sellers(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """*Your best sellers* and *All products sold* - her own sales, by product.

    Computed from her attributed orders, counted as her money counts them -
    delivered and pending, never a failed delivery (`best_sellers_for`, F02,
    ADR 0040) - so no other model's sales can reach this payload however it is
    asked for: the route takes no affiliate id, as nothing under `/api/me` does.

    `codes` is every code she has held, for the export's *Sales through
    HBA15*: the list is all time, so a code she has since given up sold on it.
    """
    from sqlalchemy import select

    from app.models.catalogue import Product
    from app.models.codes import DiscountCodePeriod
    from app.services.performance import best_sellers_for
    from app.services.wardrobe import thumbnail

    rows = best_sellers_for(db, affiliate.id)
    images = (
        {
            product.shopify_product_id: product.image_url
            for product in db.scalars(
                select(Product).where(
                    Product.shopify_product_id.in_(
                        [row.shopify_product_id for row in rows]
                    )
                )
            )
        }
        if rows
        else {}
    )
    return {
        "products": [
            {
                "shopify_product_id": row.shopify_product_id,
                "title": row.title,
                "quantity": row.quantity,
                "sales_piastres": row.sales_piastres,
                "sales": format_egp(row.sales_piastres),
                "image_url": thumbnail(images.get(row.shopify_product_id)),
            }
            for row in rows
        ],
        "codes": sorted(
            set(
                db.scalars(
                    select(DiscountCodePeriod.code).where(
                        DiscountCodePeriod.affiliate_id == affiliate.id
                    )
                )
            )
        ),
    }


@router.get("/targets")
def my_targets_view(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """What has been asked of her and what has been recorded, month by month.

    UI24. **A read and nothing else** — there is no companion `PUT` and there
    is not going to be one. What a model produced is recorded by whoever
    counted it (§6.5), and on a guaranteed minimum the recording decides money;
    a route that let the person being measured edit the measurement would be
    the one hole worth having none of.

    That is also why the writable-routes guard in `tests/test_portal_api.py`
    lists every method a model can call: adding a write here fails the suite
    until somebody writes down why.
    """
    return my_targets(db, affiliate)


@router.get("/ranking/{month}")
def my_ranking(
    month: str,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Where she stands against the other models. M02, and D03.

    **Ordered by sales; the figures shown are uses.** M02 is explicit that a
    peer value is never another model's sales, commission or salary — so the
    board carries a rank, a name and a use count, and her own sales appear only
    on her own row.

    That gap is deliberate and it has to be explained rather than hidden: two
    models can show the same uses and rank differently, because uses only break
    a tie. The screen says the order is by sales, without promising that
    matching somebody's uses would match her rank.
    """
    from app.services.performance import month_performance

    month = _month_or_400(month)
    board = month_performance(db, month)

    return {
        "month": month,
        "basis": "sales",
        "rows": [
            {
                "affiliate_id": row.affiliate_id,
                "rank": row.rank,
                # Her own name, and nobody else's - a leaderboard that names
                # everybody turns twenty colleagues into a public table.
                "name": row.name if row.affiliate_id == affiliate.id else None,
                "is_me": row.affiliate_id == affiliate.id,
                "uses": row.uses,
                # Only ever her own. M02.
                "sales_piastres": (
                    row.sales_piastres if row.affiliate_id == affiliate.id else None
                ),
                "sales": (
                    format_egp(row.sales_piastres)
                    if row.affiliate_id == affiliate.id
                    else None
                ),
            }
            for row in board
        ],
    }
