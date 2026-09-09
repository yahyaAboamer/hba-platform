"""when she actually started, and what size she wears

Two additive columns on `affiliate_profile`, both nullable, both for facts the
platform has been inferring or doing without.

## `collaboration_start_month`

**The month she actually started working with HBA**, as the business knows it.

Until now `portal.months_for` derived a model's first month from the earliest
month she has an attributed order or a payroll record in. That is a reasonable
guess and it is the wrong fact. Rule H01 says so outright: *invitation date,
code first order and platform signup are not interchangeable with collaboration
start.* Three ways it goes wrong, all of them real:

- She collaborated from January and her first order landed in March. Her
  January and February show as if she did not exist, when what they should show
  is that she sold nothing — a legitimate zero, which H01 requires stay visible.
- Her code was created on Shopify in March but she had been posting since
  January under someone else's. `codes.start_month_for` answers a different
  question — when a *code* may claim orders — and answers it correctly. It is
  not this.
- She joined in June, and a backfill attributed a January order to her code in
  error. The derived start would silently claim five months she was never here
  for.

Nullable, and deliberately not backfilled. There is no rule that recovers this
from the data — that is the whole point of the column — so an empty value means
*nobody has told us yet*, and `months_for` keeps its existing derivation until
somebody does. Filling it in is D01, through the setup interface, per model.

The check constraint is a shape check only. **`2026-13` is refused; a wrong but
well-formed month is not**, because no constraint can know when she started.

## `height_cm` and `weight_kg`

Optional measurements (rule A05). Marketing needs product sizes and sometimes
height and weight; a model supplies them if she wants to and **a missing one
never blocks an application**, which is why they are nullable with no default
rather than zero. A zero here would be a measurement.

Bounded to refuse a typo that would otherwise be read as a fact — 250cm and
400kg are not sizes, and an unbounded smallint accepts a mistyped phone number.
The bounds are wide on purpose: this is a check against nonsense, not an
opinion about bodies.

**Admins may read these and may not write them** (A05). That is enforced in the
service, not here — a column cannot know who is asking.

Revision ID: d4b81c07af22
Revises: a71f4c9be830
Create Date: 2026-09-09 21:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b81c07af22"
down_revision: Union[str, Sequence[str], None] = "a71f4c9be830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "affiliate_profile",
        sa.Column("collaboration_start_month", sa.String(length=7), nullable=True),
    )
    op.add_column(
        "affiliate_profile",
        sa.Column("height_cm", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "affiliate_profile",
        sa.Column("weight_kg", sa.SmallInteger(), nullable=True),
    )

    # Shape, not truth. `YYYY-MM` with a real month number, so a transposed
    # `2026-31` cannot sit in the column being compared against every other
    # month string in the platform and quietly sorting last.
    op.create_check_constraint(
        "affiliate_profile_start_month_well_formed",
        "affiliate_profile",
        "collaboration_start_month IS NULL OR "
        "collaboration_start_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'",
    )
    op.create_check_constraint(
        "affiliate_profile_height_sane",
        "affiliate_profile",
        "height_cm IS NULL OR (height_cm >= 100 AND height_cm <= 250)",
    )
    op.create_check_constraint(
        "affiliate_profile_weight_sane",
        "affiliate_profile",
        "weight_kg IS NULL OR (weight_kg >= 30 AND weight_kg <= 250)",
    )


def downgrade() -> None:
    """Drops three facts nothing else can reconstruct.

    Reversible in the schema sense and lossy in every other. A recorded
    collaboration start exists precisely because it could not be derived; after
    this it cannot be derived again either.
    """
    op.drop_constraint(
        "affiliate_profile_weight_sane", "affiliate_profile", type_="check"
    )
    op.drop_constraint(
        "affiliate_profile_height_sane", "affiliate_profile", type_="check"
    )
    op.drop_constraint(
        "affiliate_profile_start_month_well_formed",
        "affiliate_profile",
        type_="check",
    )
    op.drop_column("affiliate_profile", "weight_kg")
    op.drop_column("affiliate_profile", "height_cm")
    op.drop_column("affiliate_profile", "collaboration_start_month")
