"""The four settlement states, §11.1.

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


VALID_SETTLEMENT_STATES = frozenset(
    value
    for name, value in vars(SettlementState).items()
    if not name.startswith("_") and isinstance(value, str)
)
