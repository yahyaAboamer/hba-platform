import { formatEgp, moneyClass } from "../lib/money";
import type { MoneyKind, MoneyTone } from "../lib/money";

type Props = {
  piastres: number;
  /** ADR 0027. `agreed` sets it in the mono face; anything else does not. */
  kind?: MoneyKind;
  tone?: MoneyTone;
  title?: string;
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
}: Props) {
  return (
    <span className={moneyClass(kind, tone, piastres)} title={title}>
      {formatEgp(piastres)}
    </span>
  );
}
