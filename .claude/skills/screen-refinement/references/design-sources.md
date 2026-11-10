# Outside sources, and what HBA takes from them

Used on Payments (journal §2). A principle is adopted only when it also fixes
something actually seen on the screen; one secondary source alone is not
enough. When a source is read second-hand, say so in the journal.

| Source | Principle | How HBA applies it |
|---|---|---|
| GOV.UK Design System - *Warning text*, *Inset text* | Keep warnings for real consequences or they stop working; inset text is supplementary and used sparingly | The three tiers: warning / note / help, each with one look |
| Shopify Polaris - *Banner* | A warning or critical banner says how to fix the problem and carries the action | Every warning ends in its act, as a button, not a link buried in a sentence |
| Polaris and Stripe - status filters | Filters named for the state you act on; payout pages lead with amount and status | Filters with no rows hidden; labels name the actionable state (*Ready to send*) |
| Stripe - payouts timeline and trace ID | A transfer's page is about the transfer: when, reference, where | Pages titled for the thing (*Transfer*), dated by the real event (*Sent on*) |
| NN/g - confirmation dialogs (second-hand) | Confirm only irreversible acts; name the consequence; button = the act | *Approve EGP 6,400*; no extra confirm where a page or idempotent key already protects |
| NN/g - progressive disclosure | Show what most need; reveal the rest on intent | Hide empty and duplicate things; never hide amounts, consequences, irreversibility |
| Apple Human Interface Guidelines | 44pt targets; lead with the answer on small screens | 44px controls on phones; amount and next act first |
| Vercel Web Interface Guidelines (`web-design-guidelines` skill) | Forms, focus, errors, copy | Field errors with ARIA; specific labels; disabled-with-reason |

## Sources worth checking for screens not yet done

Look these up when the screen calls for them, and record what was taken:

- GOV.UK *Summary list*, *Task list*, *Error summary* - detail pages and forms.
- Polaris *Index table*, *Empty state*, *Filters* - list screens.
- Stripe Dashboard and Wise transfer pages - anything money-moving.
- WCAG 2.2 (target size 2.5.8, focus not obscured 2.4.11) - every screen.
