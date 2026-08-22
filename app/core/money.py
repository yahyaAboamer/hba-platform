"""Money primitives.

Every currency amount in this system is an integer number of piastres
(1 EGP = 100 piastres). Floating point never touches money — not in storage,
not in transport, and not in calculation.

Two rules govern the arithmetic, and both exist because the previous system
got them wrong:

1. **Multiply first, divide once.** Commission is base x rate, and dividing
   per order truncates a fraction of a piastre each time. Across a month those
   truncations become a real, silent shortfall. The numerator is therefore
   carried undivided and summed, and the single division happens at the end.

2. **Round half-up, once, on the final total.** Python's built-in round()
   rounds half to *even*, so E£10,608.50 becomes E£10,608 while E£10,609.50
   becomes E£10,610. That underpays half the time and looks arbitrary on a
   payslip. Decimal with ROUND_HALF_UP is used instead, and only at the moment
   a payout is approved.
"""

from decimal import ROUND_HALF_UP, Decimal

BASIS_POINTS = 10_000
PIASTRES_PER_POUND = 100


def _require_int(value: object, name: str) -> int:
    """Reject anything that is not a genuine integer.

    bool is excluded explicitly: it subclasses int, so True would otherwise
    pass silently and mean a rate of one basis point.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer number of piastres, got {type(value).__name__}")
    return value


def commission_numerator(base_piastres: int, rate_bp: int) -> int:
    """Return base x rate as an exact integer, deliberately undivided.

    Callers sum these across every order in a month and divide only once, via
    exact_commission_piastres. This keeps the arithmetic exact no matter how
    many orders are involved.
    """
    _require_int(base_piastres, "base_piastres")
    _require_int(rate_bp, "rate_bp")
    if base_piastres < 0:
        raise ValueError("Commission base cannot be negative")
    if not 0 < rate_bp <= BASIS_POINTS:
        raise ValueError("Commission rate must be above 0 and at most 10000 basis points")
    return base_piastres * rate_bp


def exact_commission_piastres(numerator_total: int) -> Decimal:
    """Divide the summed numerator once, preserving fractional piastres."""
    _require_int(numerator_total, "numerator_total")
    return Decimal(numerator_total) / Decimal(BASIS_POINTS)


def round_half_up_to_pounds(exact_piastres: Decimal | int) -> int:
    """Round to whole pounds, half-up, and return the result in piastres.

    Half-up rather than banker's rounding, and away from zero for negatives so
    that a credit of E£0.50 is treated the same magnitude as a payment of
    E£0.50. The result is always a multiple of 100 piastres.

    Floats are refused. Decimal(1060850.7) is 1060850.69999999995343..., and a
    value sitting near a .5 boundary would round the wrong way. Accepting a
    float here would quietly undo the exactness the rest of the module exists
    to guarantee.
    """
    if isinstance(exact_piastres, float):
        raise TypeError(
            "round_half_up_to_pounds refuses floats: pass a Decimal or an int"
        )
    if isinstance(exact_piastres, bool) or not isinstance(exact_piastres, (Decimal, int)):
        raise TypeError(
            f"expected Decimal or int, got {type(exact_piastres).__name__}"
        )
    pounds = (Decimal(exact_piastres) / PIASTRES_PER_POUND).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(pounds) * PIASTRES_PER_POUND


def format_egp(piastres: int) -> str:
    """Render piastres as a display string. Never used for calculation."""
    sign = "-" if piastres < 0 else ""
    whole, fraction = divmod(abs(int(piastres)), PIASTRES_PER_POUND)
    return f"{sign}E£{whole:,}.{fraction:02d}"
