import { formatEgp, moneyClass } from "../lib/money";
import type { MoneyKind, MoneyTone } from "../lib/money";

type Props = {
  piastres: number;
  /** ADR 0027. `agreed` sets it in the mono face; anything else does not. */
  kind?: MoneyKind;
  tone?: MoneyTone;
  title?: string;
  /**
   * Layout only — size and placement.
   *
   * The face and the colour are decided by `kind` and `tone` and are not
   * open to a caller, because the whole value of ADR 0027 is that the same
   * distinction looks the same on every screen.
   */
  className?: string;
};

/**
 * A figure, set according to whether it is real.
 *
 * Every amount in the interface goes through here, so the one distinction the
 * platform is built around — a calculation can change, an obligation cannot —
 * cannot drift apart across screens.
 *
 * §12.5: money never wraps or truncates at any width. The `nowrap` lives in
 * `.money`; if a figure does not fit, the layout gives way, never the number.
 */
export function Money({
  piastres,
  kind = "provisional",
  tone = "neutral",
  title,
  className,
}: Props) {
  return (
    <span
      className={[moneyClass(kind, tone, piastres), className]
        .filter(Boolean)
        .join(" ")}
      title={title}
    >
      {formatEgp(piastres)}
    </span>
  );
}
