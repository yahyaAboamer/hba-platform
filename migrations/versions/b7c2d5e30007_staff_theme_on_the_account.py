"""a staff member's theme, on their account

Settings audit P1 (owner approved 30 September 2026): the theme lived in one
browser's storage while the two switches beside it followed the account, so
the admin tool changed colour depending on which laptop it was opened on.

One nullable column. `NULL` means nobody chose, which reads as dark - the
default it always had. `system` follows the device's own setting, the third
option the approved mock offers.

Additive, no rewrite, and nothing reads it but the preferences route.
Downgrade drops it; the browser's own copy still holds each device's choice.

Revision ID: b7c2d5e30007
Revises: a6b1c4e20006
Create Date: 2026-09-30 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7c2d5e30007"
down_revision: Union[str, Sequence[str], None] = "a6b1c4e20006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_account", sa.Column("maintainer_theme", sa.String(6)))
    op.create_check_constraint(
        "user_account_maintainer_theme_valid",
        "user_account",
        "maintainer_theme IS NULL OR maintainer_theme IN ('dark', 'light', 'system')",
    )


def downgrade() -> None:
    op.drop_constraint("user_account_maintainer_theme_valid", "user_account", type_="check")
    op.drop_column("user_account", "maintainer_theme")
