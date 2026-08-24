"""Where an affiliate's money is sent.

Changing this is a **money-impacting change**, not a profile edit (§6.4). An
account that can silently repoint an InstaPay address can redirect an entire
payout, so it is treated with compensation-level weight.

**Append-only, with supersession.** A change writes a new row and stamps the
old one as superseded; nothing is ever updated in place. A payment made in
March must always resolve the destination that was in force in March, and an
editable destination would quietly change what a past payment appears to have
been.

The one permitted update is ``superseded_at``, which is what supersession
*means*. The trigger allows that column and nothing else - see the migration.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PayoutMethod:
    """How money reaches an affiliate."""

    #: The usual one. §13.1 collects the Payment Address URL rather than just a
    #: number, because the Pay button opens InstaPay with it pre-filled.
    INSTAPAY = "instapay"
    BANK = "bank"
    WALLET = "wallet"


VALID_METHODS = frozenset(
    value for name, value in vars(PayoutMethod).items() if not name.startswith("_")
)

_METHOD_LIST = ", ".join(f"'{method}'" for method in sorted(VALID_METHODS))


class PayoutDestination(Base):
    """One destination, valid until superseded."""

    __tablename__ = "payout_destination"
    __table_args__ = (
        CheckConstraint(
            f"method IN ({_METHOD_LIST})", name="payout_destination_method_valid"
        ),
        Index("payout_destination_affiliate_idx", "affiliate_id"),
        # The current destination is the one not yet superseded. Partial, so it
        # covers only the rows that answer "where does money go now".
        Index(
            "payout_destination_current_idx",
            "affiliate_id",
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_profile.id", ondelete="CASCADE"), nullable=False
    )

    method: Mapped[str] = mapped_column(String(20), nullable=False)

    #: The Payment Address URL, not merely the number (§13.1).
    instapay_address_url: Mapped[str | None] = mapped_column(String(500))
    #: A fallback, collected but not required.
    instapay_phone: Mapped[str | None] = mapped_column(String(40))

    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account_holder: Mapped[str | None] = mapped_column(String(200))
    bank_account_number: Mapped[str | None] = mapped_column(String(64))

    wallet_phone: Mapped[str | None] = mapped_column(String(40))

    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    #: NULL means this is the current destination.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    affiliate = relationship("AffiliateProfile", lazy="joined")

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None

    def __repr__(self) -> str:
        # Deliberately carries no address, account number or phone. A
        # destination reaching a log line or a traceback must not take
        # somebody's banking details with it.
        state = "current" if self.is_current else "superseded"
        return f"<PayoutDestination {self.id} {self.method} {state}>"
