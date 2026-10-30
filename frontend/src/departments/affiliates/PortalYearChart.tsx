
/**
 * A08. `uses` is **required**, and that is the point of writing it this way.
 *
 * It used to be optional, so `my_year` not sending it was not a mistake any
 * tool could see: Home read *37 uses* from the month card while the Uses tab
 * beside it said *this history is not available yet*, and both were behaving
 * exactly as written.
 *
 * `null` still means genuinely unknown and still draws "Not available". What
 * it can no longer mean is *nobody wired it up*.
 */
export type ChartMonth = { month: string; sales_piastres: number | null; uses: number | null; in_progress: boolean };
/*
 * The export's plot, to its numbers (`viewBox="-24 0 324 130"`): months from
 * x 8 to 292, the axis at y 102 and 88 high, three rules at 0, half and the
 * top, labelled at x 2, and the scale given headroom above the highest month
 * - 15% for sales, 35% for uses, so a bar's count fits over it.
 *
 * Two cases the export never meets and ours must: a single month (its
 * `284 * i / (n - 1)` divides by zero), drawn in the middle; and a year with
 * no sales (its `max * 1.15` is zero), drawn flat on the axis. A month with
 * no figure stays a gap, never a zero.
 *
 * **Axis text as the export's markup draws it** - rule labels at x 2, month
 * numbers at y 122, Inter 10 in the faint tier, the month being read in
 * accent. Its runtime never actually rendered them (each sat in an HTML
 * `<span>` inside SVG `<text>`); the owner asked for them back, 24 September,
 * from the real figures, never the prototype's.
 */
const LEFT = 8;
const WIDTH = 284;
const AXIS = 102;
const HEIGHT = 88;

const known = (v: number | null): v is number => v !== null && Number.isFinite(v);

/**
 * The top of the scale: the highest month plus the export's headroom.
 *
 * Uses are counts, so their top is rounded up to a whole, even number: the
 * middle rule then falls on a whole count too, and every label is exactly
 * the value its rule stands at.
 */
export function chartScale(values: (number | null)[], headroom: number, whole = false): number {
  const max = Math.max(0, ...values.filter(known));
  if (max <= 0) return 0;
  const top = max * headroom;
  return whole ? Math.max(2, Math.ceil(top / 2) * 2) : top;
}

/** A sales figure, in piastres, as a rule label: whole pounds below
 *  EGP 1,000, thousands as *K* to one place from there (*7.3K*, *15K*). */
export function salesLabel(piastres: number): string {
  const pounds = piastres / 100;
  if (pounds < 1000) return String(Math.round(pounds));
  const thousands = pounds / 1000;
  const shown = thousands >= 100 ? Math.round(thousands) : Math.round(thousands * 10) / 10;
  return `${shown}K`;
}

/** The three rules' labels, bottom up. A year of nothing labels only the axis. */
export function axisLabels(scale: number, metric: "sales" | "uses"): string[] {
  if (!scale) return ["0", "", ""];
  return [0, 0.5, 1].map((f) =>
    metric === "uses" ? String(Math.round(scale * f)) : salesLabel(scale * f),
  );
}

export function chartPoints(values: (number | null)[], headroom = 1.15) {
  const scale = chartScale(values, headroom);
  return values.map((value, index) => !known(value) ? null : {
    x: values.length === 1 ? LEFT + WIDTH / 2 : LEFT + (WIDTH * index) / (values.length - 1),
    y: AXIS - (scale ? (HEIGHT * Math.max(0, value)) / scale : 0),
  });
}
