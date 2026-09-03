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
used only on the compensation route.** Adding a code is administrative;
changing a rate is money, and the two must be gateable separately even where
today's roles happen to grant both together (ADR 0018).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.businesstime import business_month, utcnow
from app.core.periods import OPEN_ENDED
from app.core.permissions import Permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile, AffiliateStatus
from app.models.identity import UserAccount
from app.services.affiliates import (
    archive_affiliate,
    create_affiliate,
    create_house_account,
    get_affiliate,
    list_affiliates,
    readiness,
    set_status,
    update_details,
)
from app.services.codes import (
    codes_for,
    registered_codes,
    codes_with_status,
    mark_verified,
    normalise_code,
    register_code,
    replace_code,
    open_codes_for,
    retire_and_replace,
    start_month_for,
    unregistered_code_for,
)
from app.services.applications import REQUIRED_PAYOUT_FIELDS
from app.services.compensation import (
    get_terms,
    set_terms,
    terms_for,
)
from app.services.payouts import (
    current_destination,
    mask_destination,
    reveal_destination,
    set_destination,
)
from app.services.payroll import working_month
from app.services.shopify.client import (
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.shopify.discounts import REQUIRED_SCOPE, verify_discount_code

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


class RecheckCodeBody(BaseModel):
    """Ask Shopify again about a code that was not found the first time.

    ``code`` corrects a typo at the same time. Left out, the existing code is
    re-checked unchanged - the ordinary case, where the code was simply not
    created on Shopify yet.
    """

    code: str | None = Field(default=None, max_length=120)


class RegisterCodeBody(BaseModel):
    """Just the code.

    **No start month is asked for, deliberately.** There is exactly one right
    answer - the later of the platform's data horizon and the code's creation
    on Shopify - so asking a person can only produce a wrong one. Typing
    today's month would orphan every order the code had already earned, and
    nobody would notice until the model asked why their dashboard was empty.

    Verification is not asked for either. Registering looks the code up in
    Shopify, which is the same call that answers "does this exist?" - one
    action instead of two that could disagree.
    """

    code: str = Field(min_length=1, max_length=120)


class SetCompensationBody(BaseModel):
    start_month: str
    end_month: str | None = None
    compensation_type: str
    commission_rate_bp: int
    fixed_amount_piastres: int | None = None
    base_amount_piastres: int | None = None
    expected_customer_discount_bp: int | None = None


class ReplaceCodeBody(BaseModel):
    """Move a model onto a new discount code.

    ``replaces`` names which of their codes is being retired, and is only needed
    when they hold more than one - with a single code there is nothing to
    disambiguate, and asking would be noise.

    No months are asked for. The new code starts when Shopify created it (or at
    the platform horizon, whichever is later), and the old one ends the month
    before. Both are facts, not choices.
    """

    code: str = Field(min_length=1, max_length=120)
    replaces: str | None = Field(default=None, max_length=120)


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
        "phone": affiliate.phone,
        "status": affiliate.status,
        "account_kind": affiliate.account_kind,
        "is_payable": affiliate.is_payable,
        "created_at": _isoformat(affiliate.created_at),
        "archived_at": _isoformat(affiliate.archived_at),
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


def _affiliate_detail(db: Session, affiliate: AffiliateProfile) -> dict:
    """The profile plus what is true about it *this month*.

    Codes and compensation are dated; "current" means the business month right
    now, derived the same way order attribution derives it (ADR 0005).

    The payout destination is masked. This is a maintainer's screen, not the
    affiliate's own - the raw value is never returned here, only enough to
    recognise it (app/services/payouts.py).

    "Current" is the **working** month, not necessarily this one: before
    go-live the useful question is what will apply when the platform starts,
    not what applied in a month it was never responsible for.
    """
    month = working_month()
    return {
        **_affiliate_payload(affiliate),
        "current_month": month,
        "codes": codes_with_status(db, affiliate, month),
        "compensation": _compensation_payload(terms_for(db, affiliate, month)),
        "payout_destination": mask_destination(current_destination(db, affiliate)),
        # Which fields each method needs, from the one place that decides it.
        # The model's own screen already reads this; the maintainer's screen
        # correcting a destination on their behalf must agree with it, and two
        # hand-written copies would eventually not.
        "required_payout_fields": {
            method: list(fields) for method, fields in REQUIRED_PAYOUT_FIELDS.items()
        },
    }


def _get_affiliate_or_404(db: Session, affiliate_id: int) -> AffiliateProfile:
    affiliate = get_affiliate(db, affiliate_id)
    if affiliate is None:
        raise HTTPException(404, "No such affiliate")
    return affiliate


@router.get("")
def list_affiliates_route(
    include_archived: bool = False,
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

    affiliates = list_affiliates(db, include_archived=include_archived)
    month = working_month()
    setup = readiness(db, month)
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
    return {
        "affiliates": [
            {**_affiliate_payload(a), **setup.get(a.id, {}), "code": codes.get(a.id)}
            for a in affiliates
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

    Registering the code looks it up in Shopify first, exactly like
    `register_code_route` - the same call answers "does this exist?" and
    "which month does ownership start from?". A code Shopify has never heard
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
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    return _affiliate_detail(db, affiliate)


@router.patch("/{affiliate_id}")
def update_affiliate_status_route(
    affiliate_id: int,
    body: UpdateStatusBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Change an affiliate's status.

    Only status, for now: renaming or updating contact details has no service
    function yet, and this task does not add one.

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

        if body.status is None:
            pass
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
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    db.commit()
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
    start_month = start_month_for(found["created_at"])

    try:
        if body.code is not None and normalise_code(body.code) != period.code:
            replace_code(
                db,
                period,
                body.code,
                start_month=start_month,
                verified_at=verified_at,
                actor_id=actor.id,
                actor_email=actor.email,
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

    db.commit()
    return {
        "code": period.code,
        "start_month": period.start_month,
        "is_verified": period.is_verified,
        "exists_in_shopify": found["exists"],
        "shopify_status": found["status"],
    }


@router.post("/{affiliate_id}/codes", status_code=201)
def register_code_route(
    affiliate_id: int,
    body: RegisterCodeBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Give an affiliate a discount code.

    Looks the code up in Shopify, and that one call settles both questions:
    whether it exists, and which month ownership starts from.

    **A code Shopify has never heard of is still registered, unverified.** The
    business has models whose code has not been created yet, and refusing to
    record what they applied with would be unhelpful. Approval is what the
    verification gate protects - see set_status - so an unverified code cannot
    quietly become a paying one.
    """
    from app.services.shopify.sync import build_client

    affiliate = _get_affiliate_or_404(db, affiliate_id)

    try:
        found = verify_discount_code(build_client(), body.code)
    except ShopifyMissingScope as exc:
        raise HTTPException(
            403,
            f"Shopify has not granted {REQUIRED_SCOPE}, so this code cannot be "
            "checked. Add the scope, then register the code.",
        ) from exc
    except ShopifyNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ShopifyError as exc:
        # Registering blind would guess the start month, and a wrong guess
        # orphans orders silently. Better to fail while somebody is watching.
        raise HTTPException(502, f"Could not reach Shopify: {exc}") from exc

    try:
        period = register_code(
            db,
            affiliate,
            body.code,
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

    db.commit()
    return {
        "code": period.code,
        "start_month": period.start_month,
        "end_month": period.end_month,
        "is_verified": period.is_verified,
        "exists_in_shopify": found["exists"],
        "shopify_status": found["status"],
    }


@router.post("/{affiliate_id}/replace-code", status_code=201)
def replace_code_route(
    affiliate_id: int,
    body: ReplaceCodeBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """They changed their code on Shopify. Carry them across to the new one.

    Nothing about them changes: same record, same dashboard, same history. Their
    earlier months keep showing the old code and the orders it earned; later
    months show the new one. Their performance runs continuously across both.

    The old code is **ended, never rewritten**. It was live and has attributed
    orders; changing it would alter what those orders belonged to, and a month
    already calculated would silently disagree with itself.
    """
    from app.services.shopify.sync import build_client

    affiliate = _get_affiliate_or_404(db, affiliate_id)

    held = open_codes_for(db, affiliate)
    if not held:
        raise HTTPException(
            404,
            "This affiliate holds no current code to replace. Register one "
            "instead.",
        )
    if body.replaces is not None:
        wanted = normalise_code(body.replaces)
        old_period = next((p for p in held if p.code == wanted), None)
        if old_period is None:
            raise HTTPException(404, f"{wanted!r} is not a current code for this affiliate")
    elif len(held) > 1:
        raise HTTPException(
            409,
            "This affiliate holds more than one current code. Name which one "
            "is being replaced.",
        )
    else:
        old_period = held[0]

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

    if not found["exists"]:
        # Ending their current code on the strength of one Shopify has never
        # heard of would leave them earning nothing from that month on, and
        # nothing would report it.
        raise HTTPException(
            400,
            f"Shopify has no code {found['code']!r}. Create it there first - "
            "retiring the current code for one that does not exist would stop "
            "the earnings from that month with nothing to show for it.",
        )

    try:
        replacement = retire_and_replace(
            db,
            affiliate,
            old_period=old_period,
            new_code=body.code,
            new_start_month=start_month_for(found["created_at"]),
            verified_at=utcnow(),
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
            f"{body.code.strip().upper()!r} is already owned by somebody else "
            "during part of this period",
        ) from exc

    db.commit()
    return {
        "retired": {
            "code": old_period.code,
            "start_month": old_period.start_month,
            "end_month": old_period.end_month,
        },
        "took_over": {
            "code": replacement.code,
            "start_month": replacement.start_month,
            "is_verified": replacement.is_verified,
        },
    }


@router.post("/{affiliate_id}/compensation", status_code=201)
def set_compensation_route(
    affiliate_id: int,
    body: SetCompensationBody,
    actor: UserAccount = Depends(require_permission(Permission.COMPENSATION_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    try:
        terms = set_terms(
            db,
            affiliate,
            start_month=body.start_month,
            end_month=body.end_month,
            compensation_type=body.compensation_type,
            commission_rate_bp=body.commission_rate_bp,
            fixed_amount_piastres=body.fixed_amount_piastres,
            base_amount_piastres=body.base_amount_piastres,
            expected_customer_discount_bp=body.expected_customer_discount_bp,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, "These months overlap pay terms already on record for this affiliate"
        ) from exc

    db.commit()
    return _compensation_payload(terms)


@router.post("/{affiliate_id}/payout-destination/reveal")
def reveal_payout_destination_route(
    affiliate_id: int,
    actor: UserAccount = Depends(require_permission(Permission.PAYMENTS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """The real destination, for the person about to send money. ADR 0028.

    Gated on `payments.record` rather than `affiliates.view`: reading a
    profile and sending money are different acts, and only the second one
    needs the number.

    **POST, not GET.** It writes an audit row, and a request that changes
    state is not a GET however much it reads like one. It also keeps the
    affiliate id out of anywhere a URL gets logged with a 200 beside it.

    Returns only the fields that method actually needs. A bank payout does not
    hand back a wallet number that happens to be on the same row.
    """
    affiliate = _get_affiliate_or_404(db, affiliate_id)
    try:
        revealed = reveal_destination(
            db, affiliate, actor_id=actor.id, actor_email=actor.email
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    db.commit()
    return revealed


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
