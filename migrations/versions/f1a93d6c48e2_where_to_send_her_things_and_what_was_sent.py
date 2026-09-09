"""where to send her things, and what was sent

Two subjects, both from D11 and W03/W06.

## Her address, on her profile

D11, from the owner on 10 September 2026:

> It's a protected data for the models. But the admins can see it because these
> are the data that will be used when creating their orders. So her address is
> the one that we use to put inside the order details.

So the address is **not** a Shopify fact reverse-engineered into an identity.
HBA types it into the order; the platform is the source and Shopify holds the
copy. Both sides may edit it — unlike measurements, which are hers alone (A05).

`shipping_phone` is separate from `phone` deliberately. The existing `phone` is
an InstaPay fallback for *paying* her; this is the number on a *parcel*, and
they are the same number often enough that merging them would look harmless
right up until the month somebody changes one.

## What was sent, and to whom

`model_shipment` is one order matched to one model. W06: *store each matched
shipment and its line items internally; one shipment may contain many products
and its status applies to each.* The line items already exist from 03A, keyed
by order — so this table is the link and the provenance, not a second copy.

**`recipient_token` is a normalised phone, and this is not anonymisation.**
`BACKEND_CONTRACTS.md` is explicit: *do not claim an unkeyed phone hash
anonymizes predictable phone numbers.* Eleven digits with a known prefix is
guessable. The protection is that the column lives on this restricted table and
nowhere else — never in `order_index`, never in `attributed_order`, never in a
model's own payload.

## Why the link survives a phone change

W03: *preserve verified historical order links across phone changes.* The match
is written once, with the token it was decided on and how. Changing her phone
tomorrow does not re-run history — the row already says which parcel was hers,
and a later re-match reads `matched_at` and leaves a confirmed row alone.

Revision ID: f1a93d6c48e2
Revises: e7c2a5f1b930
Create Date: 2026-09-10 14:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a93d6c48e2"
down_revision: Union[str, Sequence[str], None] = "e7c2a5f1b930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Her address (D11) ────────────────────────────────────────────────────
    for column in (
        sa.Column("shipping_phone", sa.String(length=40), nullable=True),
        sa.Column("shipping_name", sa.String(length=200), nullable=True),
        sa.Column("shipping_line1", sa.String(length=300), nullable=True),
        sa.Column("shipping_line2", sa.String(length=300), nullable=True),
        sa.Column("shipping_city", sa.String(length=120), nullable=True),
        sa.Column("shipping_governorate", sa.String(length=120), nullable=True),
        sa.Column("shipping_notes", sa.String(length=500), nullable=True),
    ):
        op.add_column("affiliate_profile", column)

    # ── What was sent (W03, W06) ─────────────────────────────────────────────
    op.create_table(
        "model_shipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "shopify_order_id",
            sa.String(length=32),
            sa.ForeignKey("order_index.shopify_order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable: an unmatched parcel is an ordinary state and worth
        # recording. Most of the shop's orders are customers, and a row that
        # says "this one could not be attached, and why" is what W12's staff
        # path resolves.
        sa.Column(
            "affiliate_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_profile.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # The normalised phone the decision was made on. Not a hash, and not
        # claimed to be anonymous - see the module docstring.
        sa.Column("recipient_token", sa.String(length=20), nullable=True),
        # How it was decided, and why not where it was not.
        sa.Column("match_reason", sa.String(length=24), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        # W04. Decided from the order's *original* net, so a later cancellation
        # cannot reclassify a purchase as a gift.
        sa.Column("classification", sa.String(length=16), nullable=False),
        sa.Column("original_net_piastres", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "classification IN ('gift', 'purchase', 'unknown')",
            name="model_shipment_classification_valid",
        ),
        # A match has a token and a time; an unmatched row has a reason. The
        # constraint keeps a half-written row from reading as either.
        sa.CheckConstraint(
            "(affiliate_id IS NOT NULL AND matched_at IS NOT NULL)"
            " OR (affiliate_id IS NULL AND match_reason IS NOT NULL)",
            name="model_shipment_matched_or_explained",
        ),
        # One row per order. A parcel goes to one person.
        sa.UniqueConstraint("shopify_order_id", name="model_shipment_one_per_order"),
    )
    op.create_index(
        "model_shipment_affiliate_idx", "model_shipment", ["affiliate_id"]
    )
    op.create_index("model_shipment_token_idx", "model_shipment", ["recipient_token"])
    op.create_index(
        "model_shipment_unmatched_idx",
        "model_shipment",
        ["match_reason"],
        postgresql_where=sa.text("affiliate_id IS NULL"),
    )


def downgrade() -> None:
    """Drops her address and every recorded match.

    The matches are re-derivable by running the backfill again; the address is
    not, because it was typed by a person rather than read from anywhere.
    """
    op.drop_index("model_shipment_unmatched_idx", table_name="model_shipment")
    op.drop_index("model_shipment_token_idx", table_name="model_shipment")
    op.drop_index("model_shipment_affiliate_idx", table_name="model_shipment")
    op.drop_table("model_shipment")

    for name in (
        "shipping_notes",
        "shipping_governorate",
        "shipping_city",
        "shipping_line2",
        "shipping_line1",
        "shipping_name",
        "shipping_phone",
    ):
        op.drop_column("affiliate_profile", name)
