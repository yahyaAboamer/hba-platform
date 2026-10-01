"""the first name an invitation is addressed to

Home and emails audit D (owner approved 1 October 2026): an invitation held
only an address, so its email opened with a bare "Hi," - nobody to greet. The
admin may now give a first name with the address, and the email uses it.

One nullable column. `NULL` means nobody gave one, and the email says
"Hello," instead.

Additive, no rewrite. Downgrade drops it; an invitation without it is exactly
what every invitation was before.

Revision ID: c8d3e6f40008
Revises: b7c2d5e30007
Create Date: 2026-10-01 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c8d3e6f40008"
down_revision: Union[str, Sequence[str], None] = "b7c2d5e30007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invitation", sa.Column("name", sa.String(120)))


def downgrade() -> None:
    op.drop_column("invitation", "name")
