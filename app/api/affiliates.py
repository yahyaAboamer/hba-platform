"""The affiliate registry, over HTTP.

Every write here goes through the Phase 3 services, which is where the real
rules live - overlapping periods refused by the database, codes upper-cased,
money never floats. This layer's job is permission checks, readable errors,
and committing.

**Section 6.5: a model may never edit anything determining what they are
owed.** The `affiliate` role holds no permissions at all (app/core/permissions
.py), so every route below refuses it. That is not asserted here - it is
proven per endpoint in tests/test_affiliates_api.py, because "enforced
server-side" is a claim that needs a failing request to back it up.

**`compensation.manage` is a distinct permission from `affiliates.manage`,
used only on the pay-history route.** Adding a code is administrative;
changing a rate is money, and the two must be gateable separately even where
today's roles happen to grant both together (ADR 0018).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.models.codes import DiscountCodePeriod
from app.services.audit import record_audit
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import active_role, require_permission
from app.core.businesstime import business_month, month_add, parse_month, utcnow
from app.core.periods import OPEN_ENDED, PLATFORM_START_MONTH
from app.core.permissions import Permission, has_permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile, AffiliateStatus
from app.models.identity import UserAccount
from app.services.affiliates import (
    archive_affiliate,
    create_affiliate,
    create_house_account,
    decline_application,
    erase_affiliate,
    erase_blockers,
    get_affiliate,
    reconsider_application,
    list_affiliates,
    readiness,
    record_start_from_code,
    set_collaboration_start,
    set_status,
    update_shipping_address,
    update_details,
)
from app.services.codes import (
    code_still_changeable,
    codes_for,
    registered_codes,
    codes_with_status,
    mark_verified,
    normalise_code,
    register_code,
    replace_code,
    start_month_for,
    unregistered_code_for,
    verified_codes_for,
)
from app.services.applications import REQUIRED_PAYOUT_FIELDS
from app.services.compensation import (
    all_terms,
    arrangeable_from,
    replace_pay_history,
    terms_for,
)
from app.services.payouts import (
    destination_card,
    current_destination,
    mask_destination,
    set_destination,
)
from app.services.payroll import working_month
from app.services.portal import months_for
from app.services.targets import record_outcome
from app.services.shopify.client import (
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.shopify.discounts import REQUIRED_SCOPE, verify_discount_code
from app.services.affiliates import SHIPPING_FIELDS
from app.services.setup import setup_readiness

router = APIRouter(prefix="/api/affiliates")


class CreateAffiliateBody(BaseModel):
    #: An account created earlier, by invitation (Phase 1) or, from Phase 8,
    #: by the affiliate's own acceptance of one. This endpoint never creates
    #: a user_account itself - the plan settles that ordering explicitly.
    user_account_id: int
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    account_kind: str = "model"


class UpdateStatusBody(BaseModel):
    status: str | None = None
    reason: str | None = None
    #: Corrections to what the model submitted about themselves. People mistype
    #: their own phone numbers, and email is their login - see update_details.
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    #: The month she actually started with HBA (H01). Distinguished from "not
    #: supplied" by `collaboration_start_month_set`: sending the month as null
    #: is how it is *cleared*, and a plain omission must not do that silently.
    collaboration_start_month: str | None = Field(default=None, max_length=7)
    collaboration_start_month_set: bool = False
    #: Where HBA sends her things (D11). **Staff may write this**, unlike her
    #: measurements - it is what somebody types into an order, and she may have
    #: moved without telling the platform first. Only keys present are touched.
    shipping: dict[str, str | None] | None = None


class RecheckCodeBody(BaseModel):
    """Ask Shopify again about a code that was not found the first time.

    ``code`` corrects a typo at the same time. Left out, the existing code is
    re-checked unchanged - the ordinary case, where the code was simply not
    created on Shopify yet.
    """

    code: str | None = Field(default=None, max_length=120)


class SetPayoutDestinationBody(BaseModel):
    method: str
    instapay_address_url: str | None = None
    instapay_phone: str | None = None
    bank_name: str | None = None
    bank_account_holder: str | None = None
    bank_account_number: str | None = None
    wallet_provider: str | None = None
    wallet_phone: str | None = None


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _affiliate_payload(affiliate: AffiliateProfile) -> dict:
    return {
        "id": affiliate.id,
        "user_account_id": affiliate.user_account_id,
        "name": affiliate.name,
        #: A05: marketing needs a way to reach her. D07: there is exactly one
        #: address and it is her login, so the screens that show it say so.
        "email": affiliate.account.email,
        "phone": affiliate.phone,
        "status": affiliate.status,
        "account_kind": affiliate.account_kind,
        "is_payable": affiliate.is_payable,
        "created_at": _isoformat(affiliate.created_at),
        "archived_at": _isoformat(affiliate.archived_at),
        #: When she actually started with HBA (H01). `None` means nobody has
        #: said, and her month list falls back to a derivation - which is a
        #: different fact and one the screen should be able to say so about.
        "collaboration_start_month": affiliate.collaboration_start_month,
        #: Read here, written only by her (A05). There is no admin route into
        #: these, which is the enforcement; showing them is the whole of what
        #: marketing needs.
        "height_cm": affiliate.height_cm,
        "weight_kg": affiliate.weight_kg,
    }


def _compensation_payload(terms) -> dict | None:
    if terms is None:
        return None
    return {
        "start_month": terms.start_month,
        "end_month": terms.end_month,
        "compensation_type": terms.compensation_type,
        "commission_rate_bp": terms.commission_rate_bp,
        "fixed_amount_piastres": terms.fixed_amount_piastres,
        "base_amount_piastres": terms.base_amount_piastres,
        "expected_customer_discount_bp": terms.expected_customer_discount_bp,
    }


def _month_or_400(month: str) -> str:
    """The same refusal the payments routes give, worded the same way.

    A bad month is the caller's mistake, not the server's: `parse_month`
    raises `ValueError`, which would surface as a 500 and read as an outage.
    """
    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


def _affiliate_detail(
    db: Session,
    affiliate: AffiliateProfile,
    month: str | None = None,
    *,
    may_pay: bool = False,
) -> dict:
    """The profile plus what is true about it *this month*.

    Codes and compensation are dated; "current" means the business month right
    now, derived the same way order attribution derives it (ADR 0005).

    The payout destination is masked **unless the reader may send money**
    (ADR 0042). The approved export draws this card with the real values in
    it - *InstaPay number*, *Payment link, as submitted*, and an *Open
    InstaPay* button - and it is the same card the payments desk shows,
    because it is the same question asked from a different screen. Marketing,
    who can read this profile and cannot pay anybody, still sees the
    shortened sentence and nothing else.

    "Current" is the **working** month, not necessarily this one: before
    go-live the useful question is what will apply when the platform starts,
    not what applied in a month it was never responsible for.

    **A month may be asked for.** The profile's month-scoped sections let the
    owner look at March, and terms are dated: a model can be on commission in
    one month and a guaranteed minimum in the next. Answering every month with
    today's arrangement puts the wrong rate beside an older month's earnings,
    which is the one place on this screen where being wrong costs money.

    `current_month` keeps its meaning - the working month - and `terms_month`
    says which month the terms and codes below actually describe. Two fields,
    because a screen that conflated them is what produced the bug.
    """
    working = working_month()
    month = _month_or_400(month) if month else working
    return {
        **_affiliate_payload(affiliate),
        #: **On the profile only, deliberately.** `_affiliate_payload` is
        #: shared with the directory, and a list of twenty models does not need
        #: twenty home addresses crossing the wire to render a table of names.
        #: D11 makes this staff-readable, not staff-broadcast.
        "shipping": {field: getattr(affiliate, field) for field in SHIPPING_FIELDS},
        "current_month": working,
        "terms_month": month,
        # The preview's history floor is a server fact, not a second calendar
        # hard-coded into the browser. Collaboration can start later than it.
        "platform_start_month": PLATFORM_START_MONTH,
        #: Her months, newest first, for the profile's month control: the
        #: export offers a model only the months she was with HBA
        #: (`started`). The same rule her own portal uses (`months_for`), so
        #: the owner and the model are offered the same months for her.
        "months": months_for(db, affiliate),
        "codes": codes_with_status(db, affiliate, month),
        #: Every code she has held, oldest first, for the profile's code
        #: timeline: the list shows only this month's, so *why does she have
        #: no code?* was unanswerable without it (admin Models audit).
        "code_history": [
            {
                "code": period.code,
                "start_month": period.start_month,
                "end_month": period.end_month,
                "verified": period.shopify_verified_at is not None,
            }
            for period in db.scalars(
                select(DiscountCodePeriod)
                .where(DiscountCodePeriod.affiliate_id == affiliate.id)
                .order_by(DiscountCodePeriod.start_month)
            )
        ],
        "compensation": _compensation_payload(terms_for(db, affiliate, month)),
        #: What approval checks (ADR 0052): terms for the *working* month,
        #: whichever month the profile happens to be showing.
        "working_terms_set": terms_for(db, affiliate, working) is not None,
        "payout_destination": mask_destination(current_destination(db, affiliate)),
        #: She applied from outside Egypt and HBA arranges her payment by hand
        #: (ADR 0046). Why there is no destination, rather than a gap.
        "payout_abroad": affiliate.payout_abroad,
        #: The full card, or `None`. Served on exactly the permission the
        #: desk uses, so one rule decides who sees a real account number.
        "payout_destination_card": (
            destination_card(current_destination(db, affiliate)) if may_pay else None
        ),
        # Which fields each method needs, from the one place that decides it.
        # The model's own screen already reads this; the maintainer's screen
        # correcting a destination on their behalf must agree with it, and two
        # hand-written copies would eventually not.
        "required_payout_fields": {
            method: list(fields) for method, fields in REQUIRED_PAYOUT_FIELDS.items()
        },
        #: Why she cannot be erased, in words (ADR 0052); empty when she can.
        #: The screen offers Erase only to an admin and only when this is empty.
        "erase_blockers": erase_blockers(db, affiliate),
    }


def _get_affiliate_or_404(db: Session, affiliate_id: int) -> AffiliateProfile:
    affiliate = get_affiliate(db, affiliate_id)
    if affiliate is None:
        raise HTTPException(404, "No such affiliate")
    return affiliate


@router.get("")
def list_affiliates_route(
    include_archived: bool = False,
    month: str | None = None,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Everyone, plus whether each of them is actually set up to earn.

    The readiness flags are here rather than only on the detail screen because
    the question this list answers is "who needs me". A model with no verified
    code earns nothing and says nothing about it, and finding that by opening
    twenty profiles one at a time is how it stays unnoticed for a month.
    """
    from app.services.staff import list_pending_invitations

    from app.services.overview import content_rows
    from app.services.performance import month_performance

    affiliates = list_affiliates(db, include_archived=include_archived)
    month = _month_or_400(month) if month else working_month()
    setup = readiness(db, month)

    # **The roster's sales and content columns, from the places that already
    # answer those questions.** Sales is the models' own leaderboard figure
    # (D03), so the list, the Home panel and a model's own screen cannot tell
    # three different stories about the same month; content is the same read
    # the Home table uses.
    #
    # Neither is a payout. Nothing on this screen is money owed to anybody,
    # and nothing here recalculates any.
    sales = {row.affiliate_id: row for row in month_performance(db, month)}
    content = {row["affiliate_id"]: row for row in content_rows(db, affiliates, month)}
    # The code is how an order is recognised as somebody's, so it is how a
    # person is recognised on this list too - asked for by name during the
    # walkthrough.
    #
    # Built by inverting `registered_codes`, which already answers this set-wise
    # from the one definition of "owned in this month". A second query with its
    # own copy of that filter is precisely what `codes_for` warns against: two
    # copies eventually disagree, and the way anybody finds out is a model
    # being shown somebody else's code.
    codes = {
        affiliate_id: code
        for code, affiliate_id in registered_codes(db, month).items()
    }
    # The raw arrangement that month, for the approved roster's *Terms*
    # column. Raw, and labelled by the screen, as Targets and Payments do -
    # one table of words, not three.
    from app.services.compensation import terms_for

    arrangements = {}
    for a in affiliates:
        terms = terms_for(db, a, month)
        arrangements[a.id] = terms.compensation_type if terms else None

    # The first month anybody ever wrote terms for, for Settings' *Historical
    # setup*. One query for everybody rather than a history read per model:
    # a loop here is the shape that made the products screen slow (03D).
    #
    # Months are `YYYY-MM`, so the earliest is simply the smallest string.
    from app.models.compensation import CompensationPeriod

    # A09. **Whether she is actually set up, across every month she has.**
    #
    # The column used to compare her earliest terms month with her start
    # month, which sees neither a gap in the middle nor a guaranteed month
    # with no recorded outcome. This is the same per-month rule the profile
    # screen uses, asked for the whole roster in four queries.
    from app.services.payroll import is_historical as _is_historical
    from app.services.setup import roster_readiness

    historical_setup = roster_readiness(
        db, affiliates, working=month, is_historical=_is_historical
    )

    earliest: dict[int, str] = {}
    for affiliate_id, start_month in db.execute(
        select(CompensationPeriod.affiliate_id, CompensationPeriod.start_month)
    ).all():
        if affiliate_id not in earliest or start_month < earliest[affiliate_id]:
            earliest[affiliate_id] = start_month

    # *Needs you* (admin Models audit): who has somewhere to be paid. One
    # query for everyone; a model paid abroad has no destination by design
    # (ADR 0046) and is not missing one.
    from app.models.payouts import PayoutDestination

    with_destination = set(
        db.scalars(
            select(PayoutDestination.affiliate_id).where(
                PayoutDestination.superseded_at.is_(None)
            )
        )
    )

    # She accepted her invitation and made an account, and has not applied:
    # no longer an invitation, not yet a profile - so she was on neither list.
    joined = db.execute(
        text(
            "SELECT u.id, u.email, u.display_name, u.created_at FROM user_account u "
            "JOIN role_assignment r ON r.user_account_id = u.id AND r.role = 'affiliate' "
            "AND r.revoked_at IS NULL "
            "WHERE u.status = 'active' "
            "AND NOT EXISTS (SELECT 1 FROM affiliate_profile p WHERE p.user_account_id = u.id) "
            "ORDER BY u.created_at DESC"
        )
    ).all()
    return {
        #: The working month, whichever month was asked for: the month
        #: picker counts back from it even on a link to another month.
        "working_month": working_month(),
        "affiliates": [
            {
                **_affiliate_payload(a),
                **setup.get(a.id, {}),
                "code": codes.get(a.id),
                "month": month,
                "sales_piastres": (
                    sales[a.id].sales_piastres if a.id in sales else 0
                ),
                "uses": sales[a.id].uses if a.id in sales else 0,
                "content": content.get(a.id),
                "arrangement": arrangements.get(a.id),
                #: The first month her terms cover, for *Historical setup*.
                #:
                #: **The gap is the thing to find.** A month before her
                #: earliest terms cannot be calculated at all, so a model who
                #: started in January whose terms begin in June has five
                #: months nobody can pay her for — and that is what the column
                #: exists to show. `None` means no terms were ever written,
                #: which is the same problem for every month she has worked.
                "earliest_terms_month": earliest.get(a.id),
                #: A09. How many of her eligible months can actually be
                #: calculated, and the first one that cannot. Counts rather
                #: than a boolean, because *nearly ready* is the state this
                #: screen exists to show and a yes/no hides it.
                "historical_setup": historical_setup.get(a.id),
                #: Somewhere to send her money, or paid abroad by arrangement.
                "has_payout": a.id in with_destination or bool(a.payout_abroad),
            }
            for a in affiliates
        ],
        "joined": [
            {
                "account_id": row.id,
                "email": row.email,
                "name": row.display_name,
                "joined_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in joined
        ],
        # Invitations that have not been opened yet. They belong here rather
        # than on the staff panel: a model is not staff, and an invitation
        # nobody has accepted is still somebody this screen is responsible for.
        "invited": [
            {
                "id": invitation.id,
                "email": invitation.email,
                "expires_at": invitation.expires_at.isoformat(),
                "expired": invitation.expires_at <= utcnow(),
                # Cancelled on purpose, rather than simply lapsed. The screen
                # keeps the two apart because only one of them is worth
                # resending.
                "withdrawn": invitation.withdrawn_at is not None,
                # When it was sent. Two rows for one address are otherwise
                # indistinguishable, which is exactly the state the affiliates
                # screen was found in - several identical lines, no way to tell
                # which was which or which had been acted on.
                "created_at": invitation.created_at.isoformat(),
            }
            for invitation in list_pending_invitations(db)
            if invitation.role == "affiliate"
        ],
    }


@router.post("", status_code=201)
def create_affiliate_route(
    body: CreateAffiliateBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    try:
        affiliate = create_affiliate(
            db,
            user_account_id=body.user_account_id,
            name=body.name,
            phone=body.phone,
            account_kind=body.account_kind,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            "Could not register this affiliate - the account may not exist, "
            "or may already be registered as one",
        ) from exc

    db.commit()
    return _affiliate_payload(affiliate)


class CreateHouseAccountBody(BaseModel):
    """A code that is HBA's own, not a person's.

    Just the name and the code - the same two facts an invitation collects
    for a model, minus the invitation, because there is nobody to send one to.
    """

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=120)


@router.post("/house", status_code=201)
def create_house_account_route(
    body: CreateHouseAccountBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Bring a house account into existence, code and all, in one act.

    Three things a model's onboarding does as separate steps, each requiring
    someone to come back and press the next button - accept an invitation,
    register a code, get approved - collapse into one here, because a house
    account has nobody to do the middle steps and no reason to wait between
    the others: it has no compensation to set and no targets to record, so a
    verified code is the only thing standing between it and *active*.

    Registering the code looks it up in Shopify first - the same call answers
    "does this exist?" and "which month does ownership start from?". A code Shopify has never heard
    of is still recorded, unverified, and the account stays `pending` rather
    than silently claiming orders for a code that might be mistyped.
    """
    from app.services.shopify.sync import build_client

    try:
        affiliate = create_house_account(
            db, name=body.name, actor_id=actor.id, actor_email=actor.email
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, "A house account already exists with that name"
        ) from exc

    try:
        found = verify_discount_code(build_client(), body.code)
    except ShopifyMissingScope as exc:
        raise HTTPException(
            403,
            f"Shopify has not granted {REQUIRED_SCOPE}, so this code cannot be "
            "checked. Add the scope, then try again.",
        ) from exc
    except ShopifyNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ShopifyError as exc:
        raise HTTPException(502, f"Could not reach Shopify: {exc}") from exc

    try:
        register_code(
            db,
            affiliate,
            body.code,
            # ADR 0055: when the code was created on Shopify.
            start_month_for(found["created_at"]),
            OPEN_ENDED,
            verified_at=utcnow() if found["exists"] else None,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            f"{body.code.strip().upper()!r} is already owned by somebody else "
            "during part of this period",
        ) from exc
    record_start_from_code(db, affiliate, found, actor_id=actor.id, actor_email=actor.email)

    # The only gate on approval is a verified code (set_status enforces this
    # itself, so this call would refuse otherwise) - a house account has no
    # compensation to wait on.
    if found["exists"]:
        set_status(
            db,
            affiliate,
            AffiliateStatus.ACTIVE,
            actor_id=actor.id,
            actor_email=actor.email,
        )

    db.commit()
    return _affiliate_detail(db, affiliate)


@router.get("/{affiliate_id}")
def get_affiliate_route(
    affiliate_id: int,
    month: str | None = None,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    return _affiliate_detail(
        db,
        affiliate,
        month,
        may_pay=has_permission(active_role(db, actor), Permission.PAYMENTS_RECORD),
    )


@router.post("/joined/{account_id}/remind")
def remind_to_apply_route(
    account_id: int,
    actor: UserAccount = Depends(require_permission(Permission.INVITATIONS_SEND)),
    db: Session = Depends(get_session),
) -> dict:
    """Email somebody who made her account and has not applied yet.

    Only an account on the model role with no profile: the reminder says
    *finish your application*, which is wrong for anybody else.
    """
    from app.models.affiliates import AffiliateProfile as Profile
    from app.services.notifications import apply_reminder

    account = db.get(UserAccount, account_id)
    has_profile = account is not None and db.scalar(
        select(Profile.id).where(Profile.user_account_id == account.id)
    ) is not None
    is_model = account is not None and db.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM role_assignment "
            "WHERE user_account_id = :id AND role = 'affiliate' AND revoked_at IS NULL)"
        ),
        {"id": account.id},
    ).scalar_one()
    if account is None or has_profile or not is_model or account.status != "active":
        raise HTTPException(404, "Nobody is waiting to apply with that account.")

    sent = apply_reminder(db, account)
    record_audit(
        db,
        action="application.reminded",
        subject=f"user:{account.id}",
        actor_id=actor.id,
        actor_email=actor.email,
    )
    db.commit()
    return {"emailed": sent is not None}


class EraseBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    #: Typed by the admin as a last check: her name, exactly as shown.
    confirm_name: str


@router.post("/{affiliate_id}/erase")
def erase_affiliate_route(
    affiliate_id: int,
    body: EraseBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_ERASE)),
    db: Session = Depends(get_session),
) -> dict:
    """Erase a model who never earned anything (ADR 0052). Admin only.

    Refused while any order, payroll month, payment, parcel or proof is hers,
    and unless her name is typed back - there is no undo.
    """
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    if body.confirm_name.strip() != affiliate.name.strip():
        raise HTTPException(400, "Type her name exactly as shown to confirm.")
    try:
        erased = erase_affiliate(
            db,
            affiliate,
            reason=body.reason,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"erased": erased}


@router.patch("/{affiliate_id}")
def update_affiliate_status_route(
    affiliate_id: int,
    body: UpdateStatusBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Change an affiliate's status, details, or recorded start month.

    Three different kinds of change through one request because they are made
    on one screen, each through its own service function and each audited
    separately - a status change and a corrected phone number should never
    appear in the trail as one event.

    Archiving goes through archive_affiliate rather than a bare status write,
    because archiving also closes any code the affiliate still holds, from
    this month forward - see app/services/affiliates.py.archive_affiliate.
    """
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    try:
        update_details(
            db,
            affiliate,
            name=body.name,
            phone=body.phone,
            email=body.email,
            actor_id=actor.id,
            actor_email=actor.email,
        )

        # Deliberately not part of `update_details`. That function corrects
        # what a model typed about herself; this records a business fact about
        # when she started, which decides which months she can open at all.
        # Same request, separate audit entry, separate reason.
        #
        # **Measurements are not here and must not be.** A05 gives that write
        # to the model alone, and the enforcement is that no staff route calls
        # `update_measurements` - not a check inside one.
        if body.collaboration_start_month_set:
            set_collaboration_start(
                db,
                affiliate,
                body.collaboration_start_month,
                actor_id=actor.id,
                actor_email=actor.email,
            )

        if body.shipping is not None:
            update_shipping_address(
                db,
                affiliate,
                body.shipping,
                actor_id=actor.id,
                actor_email=actor.email,
                actor_is_staff=True,
            )

        # ADR 0052: pausing, archiving and declining each carry a written
        # reason, kept on her record and shown in her Activity.
        if body.status in (
            AffiliateStatus.INACTIVE, AffiliateStatus.ARCHIVED, AffiliateStatus.DECLINED
        ) and body.status != affiliate.status and not (body.reason or "").strip():
            raise ValueError("Give a reason. It is kept with her record.")

        erased = None
        if body.status is None:
            pass
        elif body.status == AffiliateStatus.DECLINED:
            # ADR 0058: declining deletes the application, unless something
            # about money or goods is already hers.
            erased = decline_application(
                db,
                affiliate,
                reason=body.reason or "",
                actor_id=actor.id,
                actor_email=actor.email,
            )
        elif (
            body.status == AffiliateStatus.PENDING
            and affiliate.status == AffiliateStatus.DECLINED
        ):
            reconsider_application(
                db,
                affiliate,
                actor_id=actor.id,
                actor_email=actor.email,
                reason=body.reason,
            )
        elif body.status == AffiliateStatus.ARCHIVED:
            archive_affiliate(
                db,
                affiliate,
                actor_id=actor.id,
                actor_email=actor.email,
                reason=body.reason,
            )
        else:
            set_status(
                db,
                affiliate,
                body.status,
                actor_id=actor.id,
                actor_email=actor.email,
                reason=body.reason,
            )
        # A changed sign-in email meets the unique index here rather than at
        # commit, so the refusal below can say what it was.
        db.flush()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, "That email address already belongs to another account. Nothing was saved."
        ) from exc

    db.commit()
    if erased is not None:
        return {"erased": erased, "status": AffiliateStatus.DECLINED}
    return _affiliate_payload(affiliate)


@router.post("/{affiliate_id}/recheck-code")
def recheck_code_route(
    affiliate_id: int,
    body: RecheckCodeBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Ask Shopify again about a code it did not know.

    Two things happen when it is now found: the code is marked verified, and
    its start month is corrected. Until Shopify knew the code, its creation
    date was unknown and the period fell back to the platform horizon - leaving
    that in place would claim months the code did not exist for.

    A typo is corrected here too, by supplying a different code. That rewrites
    the row rather than opening a second period: an unverified code never
    attributed anything, and leaving the wrong one behind would keep it holding
    ownership that blocks the right person from claiming it.
    """
    from app.services.shopify.sync import build_client

    affiliate = _get_affiliate_or_404(db, affiliate_id)
    period = unregistered_code_for(db, affiliate)
    # ADR 0058: while her application waits and nothing is counted to her, a
    # confirmed code may be changed too - a mistyped code that happens to
    # exist on Shopify otherwise had no fix but declining her.
    changeable = body.code is not None and code_still_changeable(db, affiliate)
    if period is None and changeable:
        period = next(iter(verified_codes_for(db, affiliate)), None)
    if period is None:
        raise HTTPException(
            404,
            "This affiliate has no unverified code. A code Shopify has already "
            "confirmed is not re-checked - it may have attributed orders.",
        )

    try:
        found = verify_discount_code(build_client(), body.code or period.code)
    except ShopifyMissingScope as exc:
        raise HTTPException(
            403,
            f"Shopify has not granted {REQUIRED_SCOPE}, so this code cannot be "
            "checked. Add the scope, then try again.",
        ) from exc
    except ShopifyNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ShopifyError as exc:
        raise HTTPException(502, f"Could not reach Shopify: {exc}") from exc

    verified_at = utcnow() if found["exists"] else None
    # ADR 0055: when the code was created on Shopify, never its "Active from"
    # (a duplicated discount copies that). Her start month uses the same date.
    start_month = start_month_for(found["created_at"])

    try:
        if body.code is not None and normalise_code(body.code) != period.code:
            # Her start taken from the code being replaced follows the new
            # one; a start somebody typed is left alone (ADR 0058).
            if affiliate.collaboration_start_month == period.start_month and period.is_verified:
                affiliate.collaboration_start_month = None
            replace_code(
                db,
                period,
                body.code,
                start_month=start_month,
                verified_at=verified_at,
                actor_id=actor.id,
                actor_email=actor.email,
                while_pending=changeable,
            )
        elif found["exists"]:
            mark_verified(
                db,
                period,
                verified_at=verified_at,
                start_month=start_month,
                actor_id=actor.id,
                actor_email=actor.email,
            )
        db.flush()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            f"{(body.code or period.code).strip().upper()!r} is already owned "
            "by somebody else during part of this period",
        ) from exc

    # ADR 0053: confirming her code is when her start month becomes known -
    # written last, once nothing above can still refuse.
    record_start_from_code(db, affiliate, found, actor_id=actor.id, actor_email=actor.email)
    db.commit()
    return {
        "code": period.code,
        "start_month": period.start_month,
        "is_verified": period.is_verified,
        "exists_in_shopify": found["exists"],
        "shopify_status": found["status"],
    }


@router.put("/{affiliate_id}/payout-destination")
def set_payout_destination_route(
    affiliate_id: int,
    body: SetPayoutDestinationBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Point an affiliate's money somewhere new.

    Returns the destination **masked**, even though the caller just typed the
    raw value themselves. Echoing it back is an unnecessary second place it
    could end up logged - a response body, unlike a request body, tends to get
    captured by more things.
    """
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    try:
        destination = set_destination(
            db,
            affiliate,
            method=body.method,
            instapay_address_url=body.instapay_address_url,
            instapay_phone=body.instapay_phone,
            bank_name=body.bank_name,
            bank_account_holder=body.bank_account_holder,
            bank_account_number=body.bank_account_number,
            wallet_provider=body.wallet_provider,
            wallet_phone=body.wallet_phone,
            approved_by=actor.id,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return mask_destination(destination)


class PayHistoryPeriodBody(BaseModel):
    """One run of months on one arrangement.

    `end_month` absent means *until further notice*, and only the last period
    may leave it out - the service refuses the rest.
    """

    start_month: str
    end_month: str | None = None
    compensation_type: str
    commission_rate_bp: int
    fixed_amount_piastres: int | None = None
    base_amount_piastres: int | None = None
    expected_customer_discount_bp: int | None = None


def _period_as_sent(period: PayHistoryPeriodBody) -> dict:
    """The period, without a discount the client never mentioned.

    `model_dump` fills every default, so an omitted discount arrived as an
    explicit `None` and wiped the stored one on each save - the terms screen
    never sends it. Absent now means *unchanged* (`replace_pay_history`).
    """
    raw = period.model_dump()
    if "expected_customer_discount_bp" not in period.model_fields_set:
        del raw["expected_customer_discount_bp"]
    return raw


class PayHistoryBody(BaseModel):
    """A model's whole pay history, as one act.

    ADR 0036. `outcomes` maps a month to *met* or *missed*, for the months
    before go-live on a guaranteed minimum - the only thing the old dashboard
    kept about a target. Every other month records what was produced, on the
    Targets screen, and this refuses to take one.
    """

    periods: list[PayHistoryPeriodBody]
    outcomes: dict[str, str] = Field(default_factory=dict)


def _start_source(db: Session, affiliate: AffiliateProfile, sold_in: set[str]) -> str:
    """Where her first arrangeable month came from: `code`, `recorded`,
    `first_sale` or `none` (ADR 0055).

    Read from the audit entry that last set her start, which is the only place
    that says whether Shopify or a person gave it (ADR 0053 writes
    ``"from": "shopify_code"`` there).
    """
    from app.models.audit import AuditEvent

    if affiliate.collaboration_start_month is None:
        return "first_sale" if sold_in else "none"
    after = db.scalar(
        select(AuditEvent.after_json)
        .where(AuditEvent.subject == f"affiliate:{affiliate.id}")
        .where(AuditEvent.action == "affiliate.collaboration_start_set")
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )
    return "code" if (after or {}).get("from") == "shopify_code" else "recorded"


def _her_code(db: Session, affiliate: AffiliateProfile) -> str | None:
    """The code she holds now, for the line that says where her start came from."""
    from app.services.codes import open_codes_for

    held = open_codes_for(db, affiliate)
    return held[0].code if held else None


def _pay_history_payload(db: Session, affiliate: AffiliateProfile) -> dict:
    """Every month the editor draws, and what is already true of each.

    **One call, not one per month.** The screen shows nine months at once for
    twenty-one models in a sitting; asking per month would be nine round trips
    to draw a strip that has not changed.
    """
    from app.models.attributed_orders import AttributedOrder
    from app.models.payroll import CalculationState, PayrollMonth
    from app.models.targets import MonthlyTarget
    from app.services.payroll import go_live_month, is_historical

    working = working_month()

    sold_in = set(
        db.scalars(
            select(AttributedOrder.business_month)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .distinct()
        )
    )
    approved = set(
        db.scalars(
            select(PayrollMonth.month)
            .where(PayrollMonth.affiliate_id == affiliate.id)
            .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
        )
    )
    outcomes = {
        row.month: row.recorded_outcome
        for row in db.scalars(
            select(MonthlyTarget).where(
                MonthlyTarget.affiliate_id == affiliate.id
            )
        )
        if row.recorded_outcome is not None
    }

    # ADR 0055 (replacing 0052's twelve months ahead): only months that have
    # begun are listed. A month that has not begun cannot be decided yet; when
    # it begins it takes the terms of the month before it, because the run
    # reaching the working month is saved open-ended (`horizon_month`).
    horizon = working

    periods = all_terms(db, affiliate)
    covers = {}
    for period in periods:
        month = period.start_month
        while month <= (period.end_month or horizon):
            covers[month] = period
            month = month_add(month, 1)

    months = []
    month = PLATFORM_START_MONTH
    while month <= horizon:
        terms = covers.get(month)
        months.append(
            {
                "month": month,
                # **What the strip hatches.** A month she did not sell in is
                # not hers to arrange, and offering it as a choice invites
                # somebody to fill in a year of arrangements for months that
                # never existed.
                "has_orders": month in sold_in,
                # Locked, and the reason is worth carrying: an approved month
                # was calculated from these terms, and changing them now would
                # change what it was worth after the money moved.
                "approved": month in approved,
                # Not reached yet: arrangeable, never sold in (ADR 0052).
                "future": month > working,
                # ADR 0036. Before go-live, so a guaranteed minimum here
                # records an outcome rather than counts.
                "settled_outside": is_historical(month),
                "terms": _compensation_payload(terms),
                "outcome": outcomes.get(month),
            }
        )
        month = month_add(month, 1)

    return {
        "affiliate_id": affiliate.id,
        "name": affiliate.name,
        "working_month": working,
        #: The last month listed; a run reaching it is saved open-ended.
        "horizon_month": horizon,
        "go_live_month": go_live_month() or None,
        # **The verdict, beside the facts.** The months above say what is
        # recorded; this says whether it is enough, per month, and what is
        # missing where it is not (H06, and V09 in `DESIGN_REVIEW.md`).
        #
        # Computed, never stored. A first terms record does not prove
        # readiness and neither would a flag written when somebody looked.
        "readiness": setup_readiness(
            db, affiliate, working=working, is_historical=is_historical
        ),
        # The earliest month she has an order in. `null` for a model who has
        # never sold, where there is no history to backfill and the screen
        # offers the one-arrangement form instead.
        "joined_month": min(sold_in) if sold_in else None,
        # **The first month that is hers to arrange** (A06, H01/H04/H05).
        #
        # The editor used `joined_month` for this, which is the first month she
        # *sold* in - and the two are different for every model who was signed
        # before she made a sale. Somebody who joined in January and first sold
        # in March could not be given January or February pay at all: the grid
        # would not offer them, and a fixed salary for those months is exactly
        # the arrangement that needs recording, because there are no
        # commissions to stand in for it.
        #
        # Her collaboration start is the recorded answer to *when did she start
        # with us*, so it is the one used. Floored at the platform's own first
        # month because nothing before that is representable, and falling back
        # to the first sale and then to the working month, so a model with
        # neither still gets an arrangeable month rather than an empty grid.
        #
        # Decided here rather than in the browser: which months a person may
        # arrange is a rule, and a rule with two implementations is a rule with
        # two answers.
        "arrangeable_from": arrangeable_from(db, affiliate, working),
        # **Where that month came from** (ADR 0055), so whoever sets her terms
        # can see when she started and why: `code` - her code's start on
        # Shopify; `recorded` - typed on her profile; `first_sale` - nothing
        # recorded, so her first order; `none` - nothing at all yet.
        "start_source": _start_source(db, affiliate, sold_in),
        "code": _her_code(db, affiliate),
        "months": months,
        "periods": [_compensation_payload(row) for row in periods],
    }


@router.get("/{affiliate_id}/pay-history")
def pay_history_route(
    affiliate_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.COMPENSATION_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """What she has been paid on, month by month, for the editor to open on."""
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    return _pay_history_payload(db, affiliate)


@router.put("/{affiliate_id}/pay-history")
def set_pay_history_route(
    affiliate_id: int,
    body: PayHistoryBody,
    actor: UserAccount = Depends(require_permission(Permission.COMPENSATION_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Write her whole pay history, and the outcomes that go with it. ADR 0036.

    **One transaction.** The arrangements and the target outcomes are one
    decision on the screen and commit together here - a history written without
    its outcomes leaves every guarantee month blocked on a target nobody can
    now record from this screen, which is a state the maintainer would have to
    discover from the payroll page.
    """
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    try:
        replace_pay_history(
            db,
            affiliate,
            [_period_as_sent(period) for period in body.periods],
            actor_id=actor.id,
            actor_email=actor.email,
        )
        for month, outcome in sorted(body.outcomes.items()):
            record_outcome(
                db,
                affiliate,
                month,
                outcome=outcome,
                actor_id=actor.id,
                actor_email=actor.email,
            )
    except (ValueError, TypeError) as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, "These months overlap pay terms already on record for this affiliate"
        ) from exc

    db.commit()
    return _pay_history_payload(db, affiliate)


@router.get("/{affiliate_id}/wardrobe")
def affiliate_wardrobe_route(
    affiliate_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """The same wardrobe the model sees, on her profile.

    W08: *product and model views use the same records.* Literally the same
    function — two readings of one truth cannot disagree, and a wardrobe that
    differs between her screen and yours is the argument nobody can settle.
    """
    from app.services.wardrobe import wardrobe_for

    affiliate = _get_affiliate_or_404(db, affiliate_id)
    return wardrobe_for(db, affiliate.id)


@router.get("/{affiliate_id}/orders/{month}")
def affiliate_orders_route(
    affiliate_id: int,
    month: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Her orders for one month, for the profile's *Performance* section.

    The approved profile lists them - order, date, status, net sales and the
    commission each was worth - and the commission per order is arithmetic
    this codebase does on the server only. **The same function the model's own
    orders screen reads** (`my_orders`), so the two views of one order cannot
    tell different stories; no customer appears in either, because the index
    never stored one.
    """
    from app.services.portal import my_orders

    affiliate = _get_affiliate_or_404(db, affiliate_id)
    return {"month": _month_or_400(month), "orders": my_orders(db, affiliate, month)}


@router.get("/{affiliate_id}/record")
def affiliate_record_route(
    affiliate_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Her content record and her agreed months, for the profile.

    The approved profile's *Targets* section is a table of every month - what
    was asked, what was recorded, how it ended - and its *Payments* section a
    table of every agreed month with what was paid against it. Both are what
    the model's own screens already read (`my_targets`, `my_payments`), so the
    profile and her phone are two readings of one record.

    Months nobody has agreed are left out of `statements`, exactly as they are
    on her screen: a forecast is not a debt, and a table of amounts under a
    *State* heading would present one as though it were.
    """
    from app.services.portal import my_payments, my_targets

    affiliate = _get_affiliate_or_404(db, affiliate_id)
    return {
        "targets": my_targets(db, affiliate)["months"],
        "statements": my_payments(db, affiliate)["months"],
    }
