"""A request to feature a product.

W09 and W10. **Passive guidance, and deliberately nothing more.**

W09 spells out what it must not become: *no model Done button, acknowledgement,
completion tracking or automatic target change.* That list is the design. A
request is something marketing writes and a model reads; the moment it grows a
state per model it becomes a task system, and targets already are one.

So there is no `acknowledged_at`, no `completed_by`, no per-model row at all.
One request per product, and who sees it is computed from her wardrobe every
time it is asked (W10) rather than stored - eligibility *changes with current
shipment state*, and a stored audience would be wrong the moment a replacement
shipped.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FeatureRequest(Base):
    """What marketing would like said about one product."""

    __tablename__ = "product_feature_request"

    #: One per product. A second request for the same product would be two
    #: things to read about one garment, and nothing decides which wins.
    shopify_product_id: Mapped[str] = mapped_column(String(32), primary_key=True)

    #: Optional since D12 - a product can be featured on its picture alone.
    message: Mapped[str | None] = mapped_column(Text)

    #: W09: marketing can *make it visible, hide it, or remove it*. Hidden is
    #: not removed - a request being drafted, or paused, is not the same as one
    #: that was withdrawn, and conflating them loses the wording.
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
