"""What a model was asked to produce, what they produced, and who confirmed it.

§15. For most models this is a management record. For a `base_guarantee` model it
**decides what they are paid** (§9.5), and the same table serves both — the
difference lives entirely in the compensation type, not here.

## Three states, and only one of them is a boolean

    requirements set, nothing recorded   nobody knows what they did
    recorded                             achieved, or not
    recorded and verified                a second person confirmed the numbers

## A fourth shape, for months that happened before the platform

ADR 0036. The business knows whether March's target was met. It does not have
March's video and story counts, and it never will - they were kept on the old
dashboard, which recorded an outcome and not much else.

Inventing counts to reach a known outcome would be **fabricating evidence for a
figure that decides money**: eight videos typed to justify a guarantee nobody
can now check. So a backfilled month carries `recorded_outcome` instead - the
answer by itself - and carries **no requirements and no actuals at all**, which
is how the model's own screen knows to say the numbers were not kept rather
than to draw a bar against a zero.

The two shapes never mix. A row has requirements and may have actuals, **or**
it has an outcome and neither; the check constraint refuses anything between,
because a row with a requirement of 8 and an outcome of *met* invites the
question "met against what?" and has no answer.

"Not achieved" and "not yet recorded" are different answers with different
consequences (§11.3): the first pays their commission and approves the month, the
second **blocks it**. That is why `actual_videos` and `actual_stories` are
nullable and the requirements are not - a requirement of zero is a real answer
meaning *nothing was asked of them*, and it must stay distinguishable from nobody
having asked.

## One row per model per month

Enforced by the database. Two rows would be two answers to "did they achieve
August?", and whichever the query happened to read first would decide a payment.

## Two fields today, and that is a decision

Videos and stories, because that is what Sara tracks (confirmed 26 August 2026).
HBA wants named numeric fields it defines itself eventually; §3 of the
specification records why that is not V1 and what it would cost. Nothing here
blocks it - the achieved rule is *every requirement met*, which generalises to any
number of fields unchanged.

## No `verification_status` column

§8 lists one. `verified_at` already carries the answer, and two representations of
one fact can disagree: a row with `verified_at` set and a status saying
`unverified` is a bug nobody would see until a guarantee failed to apply. The
field list in §8 is explicitly indicative, so the timestamp is the truth and
``is_verified`` reads it.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


#: ADR 0036. The two answers the old dashboard kept about a month.
OUTCOME_MET = "met"
OUTCOME_MISSED = "missed"
VALID_OUTCOMES = frozenset({OUTCOME_MET, OUTCOME_MISSED})


class MonthlyTarget(Base):
    """One model's content requirement for one month."""

    __tablename__ = "monthly_target"
    __table_args__ = (
        # §17. Two answers to "did they achieve August?" is one too many.
        UniqueConstraint("affiliate_id", "month", name="monthly_target_one_per_month"),
        CheckConstraint(
            "required_videos >= 0 AND required_stories >= 0",
            name="monthly_target_requirements_not_negative",
        ),
        CheckConstraint(
            "(actual_videos IS NULL OR actual_videos >= 0) AND "
            "(actual_stories IS NULL OR actual_stories >= 0)",
            name="monthly_target_actuals_not_negative",
        ),
        # Recording is both numbers or neither. A half-recorded month is not a
        # third state anybody has a rule for, and "they did 8 videos and an
        # unknown number of stories" cannot answer whether they achieved.
        CheckConstraint(
            "(actual_videos IS NULL) = (actual_stories IS NULL)",
            name="monthly_target_actuals_recorded_together",
        ),
        # Confirming numbers nobody has recorded is confirming nothing, and it
        # would unlock a guarantee on an empty month. A backfilled month
        # (ADR 0036) satisfies this with its outcome: the outcome *is* what was
        # recorded, and there are no numbers behind it to confirm separately.
        CheckConstraint(
            "verified_at IS NULL "
            "OR actual_videos IS NOT NULL "
            "OR recorded_outcome IS NOT NULL",
            name="monthly_target_cannot_verify_the_unrecorded",
        ),
        CheckConstraint(
            "recorded_outcome IS NULL OR recorded_outcome IN ('met', 'missed')",
            name="monthly_target_outcome_valid",
        ),
        # ADR 0036. The two shapes of a target row, and nothing between them.
        #
        # An ordinary month has requirements and may have actuals. A month from
        # before the platform has an outcome and neither - because the counts
        # were never kept, and a row carrying both a requirement and an outcome
        # asks "met against what?" of a screen that has no way to answer.
        CheckConstraint(
            "(recorded_outcome IS NULL"
            " AND required_videos IS NOT NULL"
            " AND required_stories IS NOT NULL)"
            " OR (recorded_outcome IS NOT NULL"
            " AND required_videos IS NULL"
            " AND required_stories IS NULL"
            " AND actual_videos IS NULL"
            " AND actual_stories IS NULL)",
            name="monthly_target_counts_or_an_outcome_never_both",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_profile.id", ondelete="CASCADE"), nullable=False
    )

    #: YYYY-MM, matching every other dated thing here. A target belongs to a
    #: month, not to a day in it.
    month: Mapped[str] = mapped_column(String(7), nullable=False)

    #: What they were asked for. Zero is a real answer - *nothing was asked of
    #: them* - and stays distinguishable from nobody having asked.
    #:
    #: `NULL` on a backfilled month only (ADR 0036), where the requirement was
    #: never kept and the row carries `recorded_outcome` instead. The check
    #: constraint above is what stops that nullability leaking into an ordinary
    #: month, where an absent requirement would silently make every target
    #: achievable.
    required_videos: Mapped[int | None] = mapped_column(Integer)
    required_stories: Mapped[int | None] = mapped_column(Integer)

    #: What they produced. NULL means nobody has recorded it yet - which blocks
    #: approval, where merely missing the target does not (§11.3).
    actual_videos: Mapped[int | None] = mapped_column(Integer)
    actual_stories: Mapped[int | None] = mapped_column(Integer)

    #: ADR 0036. *met* or *missed*, for a month that happened before the
    #: platform - the whole of what the old dashboard kept, entered by the
    #: person who knows it.
    #:
    #: **Only ever set on a month before go-live**, which the service enforces
    #: rather than the database: go-live is configuration, differs between
    #: staging and production, and a constraint that moves with an environment
    #: variable is not a constraint.
    recorded_outcome: Mapped[str | None] = mapped_column(String(8))

    recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: **When** a second person confirmed the numbers, not merely that somebody
    #: did. "Verified, by whom, eight months ago" is a different answer from
    #: "verified", and only one of them can be audited.
    verified_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    affiliate = relationship("AffiliateProfile", lazy="joined")

    @property
    def is_backfilled(self) -> bool:
        """ADR 0036. An outcome from before the platform, with no counts behind it.

        Read by every screen that would otherwise draw a bar: there is nothing
        to draw, and a bar against a missing requirement reads as zero asked
        for and zero delivered.
        """
        return self.recorded_outcome is not None

    @property
    def is_recorded(self) -> bool:
        """Has anybody said how the month went?

        Two ways to have said it. An ordinary month says it in counts; a month
        from before the platform says it as an outcome, which is all anybody
        has. Both answer the question this gates - *does approval block?* - and
        §11.3 blocks on **nobody having looked**, never on how it went.
        """
        if self.is_backfilled:
            return True
        return self.actual_videos is not None and self.actual_stories is not None

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    @property
    def is_achieved(self) -> bool | None:
        """Every requirement met - or ``None`` when nobody has recorded it.

        The ``None`` is the point. "Not achieved" pays their commission and
        approves the month; "not yet recorded" blocks it. A boolean cannot
        express both, and collapsing them would silently approve a month nobody
        had looked at.

        **Every** requirement, not most of them. Confirmed with HBA on
        26 August 2026: eight videos and four of five stories is not achieved.
        §9.5 has no fractional guarantee.
        """
        if self.is_backfilled:
            # The answer itself, not a comparison. There are no counts to
            # compare and there never were (ADR 0036).
            return self.recorded_outcome == OUTCOME_MET
        if not self.is_recorded:
            return None
        return (
            self.actual_videos >= self.required_videos
            and self.actual_stories >= self.required_stories
        )

    def __repr__(self) -> str:
        return f"<MonthlyTarget affiliate={self.affiliate_id} {self.month}>"
