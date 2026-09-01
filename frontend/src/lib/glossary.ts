/**
 * §16, Phase 10 Batch C. Eight files, checked directly rather than estimated,
 * each explain at least one of these words in their own way at the moment a
 * screen needs it - `Money.tsx`, `AffiliateDetail.tsx`, `Compensation.tsx`,
 * `MyMonth.tsx`, `MyOrders.tsx`, `Orders.tsx`, `Payroll.tsx`, `Targets.tsx`.
 * None of those explanations are wrong; none of them are guaranteed to keep
 * agreeing with each other five phases from now. This is where the words get
 * defined once, in one place, for the maintainer and a model alike - the
 * definitions do not differ by who is reading.
 *
 * Not a replacement for the inline explanations. Each of those stays exactly
 * where it is; this is the page reached when a tooltip is not enough.
 */
export type GlossaryTerm = {
  id: string;
  term: string;
  definition: string;
};

export const GLOSSARY_TERMS: GlossaryTerm[] = [
  {
    id: "pending",
    term: "Pending",
    definition:
      "An order still travelling, or one with an open return or exchange. Shown, never hidden - it is not counted yet, but it is coming.",
  },
  {
    id: "void",
    term: "Void",
    definition:
      "An order that was cancelled, fully refunded, or never delivered. It pays nothing, and it is not a mistake or a penalty - it simply never became a sale.",
  },
  {
    id: "carried-forward",
    term: "Carried forward",
    definition:
      "An order sold in one month but still settling when that month closed, so it is paid in whichever month it actually finishes - at its own month's rate, added on top of that later month, never inside a guarantee comparison.",
  },
  {
    id: "guaranteed-minimum",
    term: "Guaranteed minimum",
    definition:
      "A floor under a month's pay for models on that arrangement. It only applies in a month where targets were both met and confirmed, and it is never added on top of commission - whichever is larger is what is paid, not both.",
  },
  {
    id: "provisional",
    term: "Provisional",
    definition:
      "A figure that can still change, because the month it belongs to has not closed yet. Shown in a different typeface from an agreed figure on purpose, so the two are never mistaken for each other.",
  },
  {
    id: "historical",
    term: "Historical",
    definition:
      "A month from before the platform existed. The sales are real and counted the same as any other month; there is no commission figure, because those months were paid the old way and their rate is not something this platform can state correctly.",
  },
  {
    id: "settled",
    term: "Settled",
    definition:
      "A month that has been agreed and fully paid - the obligation and what was actually sent match, with nothing outstanding either direction.",
  },
  {
    id: "verified",
    term: "Verified",
    definition:
      "A discount code Shopify has confirmed actually exists. An unverified code can still be recorded, but it cannot be approved - a code that turns out to be mistyped would otherwise attribute nothing, silently.",
  },
];
