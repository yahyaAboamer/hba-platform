"""The five settlement states, §11.1.

Separated from the ledger so the *names* have one home. Calculation state and
settlement state were a single column in the old dashboard, which is what
produced the awkward "Approved · Partially paid" - and worse, a stored value
that could disagree with the payments it was computed from.

**These are derived, never stored.** There is no column anywhere holding one of
these strings; every use computes it from the ledger.
"""


class SettlementState:
    """Has the money moved?"""

    #: Agreed, and nothing has been paid against it.
    UNPAID = "unpaid"

    #: Some of it has.
    PARTIALLY_PAID = "partially_paid"

    #: All of it has.
    SETTLED = "settled"

    #: More than all of it. Not an error - a rounding split, a transfer fee
    #: covered, or a month reopened to a lower figure after it was paid
    #: (§11.5). It is reported so somebody can decide on a credit or a
    #: write-off, which is a judgement the platform does not make.
    OVERPAID = "overpaid"

    #: No agreed figure to settle against: never approved, or reopened. **Not
    #: the same as `unpaid`** - saying "nothing outstanding" about a month that
    #: may have been paid in full against a superseded version is the most
    #: misleading answer available.
    NOT_APPROVED = "not_approved"

    #: Before go-live. Agreed and frozen like any other month, and **paid
    #: outside the platform months ago** (ADR 0036).
    #:
    #: Not `settled`, though the balance is the same zero. `settled` means
    #: *this platform sent the money and the ledger can show you when*; there
    #: is no transfer here to show, and a screen offering to reconcile one
    #: would be offering to pay a second time.
    #:
    #: This state is what replaced the blocker that used to refuse approval.
    #: ADR 0014 kept these months safe by refusing to calculate them; the
    #: safety now comes from the balance being structurally zero, which
    #: survives somebody approving the month - a blocker does not.
    SETTLED_EXTERNALLY = "settled_externally"

    @staticmethod
    def of(owed_piastres: int, covered_piastres: int) -> str:
        """Which state a figure and its coverage amount to.

        **Equality is checked before emptiness**, so a month that owes nothing
        and has been paid nothing is `settled` rather than `unpaid`. A model
        with no sales in a month is not carrying a debt of zero, and showing
        one on their row would have somebody chasing it.
        """
        if covered_piastres > owed_piastres:
            return SettlementState.OVERPAID
        if covered_piastres == owed_piastres:
            return SettlementState.SETTLED
        if covered_piastres <= 0:
            return SettlementState.UNPAID
        return SettlementState.PARTIALLY_PAID

    @staticmethod
    def of_balance(balance_piastres: int, paid_piastres: int) -> str:
        """The same question, asked of a balance that adjustments have closed.

        `of` compares two totals, which works only while every part of the
        month pushes in one direction. It stops working once an adjustment can
        close a difference from either side (ADR 0035): a month settled by a
        write-off has `covered` far below `owed` and is not `partially_paid`.

        So the balance decides, and `paid` only separates *nothing has been
        sent* from *some has*. Zero is `settled` whether it arrived there by a
        transfer, by an adjustment, or by there being nothing to settle.
        """
        if balance_piastres < 0:
            return SettlementState.OVERPAID
        if balance_piastres == 0:
            return SettlementState.SETTLED
        if paid_piastres <= 0:
            return SettlementState.UNPAID
        return SettlementState.PARTIALLY_PAID


VALID_SETTLEMENT_STATES = frozenset(
    value
    for name, value in vars(SettlementState).items()
    if not name.startswith("_") and isinstance(value, str)
)
