"""The affiliate registry.

Business data for an affiliate, hanging off a ``user_account`` rather than
replacing it (ADR 0006). Identity, sign-in and roles stay in one place; this is
who the person is to the business.

The account always exists before the profile does. An invitation creates
nothing; accepting it creates the account, and the profile is filled in from
there. So ``user_account_id`` is not nullable and needs no placeholder.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AccountKind:
    """What sort of thing this affiliate is."""

    MODEL = "model"

    #: HBA's own code - HBA10. A real code used by real customers, so it needs a
    #: working dashboard and Shopify verification like any other. But it is not
    #: a person, so it is **excluded from payable totals and from rankings**.
    #:
    #: Replaces the old system's `code_type='test'`, which described the code
    #: rather than the account and confused everyone who met it. A house code is
    #: not a test code; it takes real money from real customers.
    HOUSE = "house"


class AffiliateStatus:
    """Where an affiliate is in their life with the business."""

    PENDING = "pending"      # applied, not yet approved
    ACTIVE = "active"        # earning
    INACTIVE = "inactive"    # not earning, may return
    ARCHIVED = "archived"    # gone; history must still resolve


VALID_KINDS = frozenset(
    value for name, value in vars(AccountKind).items() if not name.startswith("_")
)
VALID_STATUSES = frozenset(
    value for name, value in vars(AffiliateStatus).items() if not name.startswith("_")
)

_KIND_LIST = ", ".join(f"'{kind}'" for kind in sorted(VALID_KINDS))
_STATUS_LIST = ", ".join(f"'{status}'" for status in sorted(VALID_STATUSES))


class AffiliateProfile(Base):
    """An affiliate, as the business knows them."""

    __tablename__ = "affiliate_profile"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_STATUS_LIST})", name="affiliate_profile_status_valid"
        ),
        CheckConstraint(
            f"account_kind IN ({_KIND_LIST})", name="affiliate_profile_kind_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Unique: one profile per account. Someone is an affiliate or they are not.
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Collected as an InstaPay fallback (§13.1), not required to exist.
    phone: Mapped[str | None] = mapped_column(String(40))

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AffiliateStatus.PENDING
    )
    account_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AccountKind.MODEL
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    #: When they were archived. Archiving is a status; this is when it happened,
    #: and it is what a code period is closed against (see the Phase 3 plan).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account = relationship("UserAccount", lazy="joined")

    @property
    def is_payable(self) -> bool:
        """Whether this affiliate can ever be owed money.

        A house account never can. Checked here rather than at each call site,
        so "exclude the house code" is one rule in one place instead of a
        condition somebody eventually forgets.
        """
        return self.account_kind != AccountKind.HOUSE

    def __repr__(self) -> str:
        return (
            f"<AffiliateProfile {self.id} {self.name!r} "
            f"{self.account_kind}/{self.status}>"
        )
