"""Things that did not break, but might.

The platform prevents failures constantly: a duplicate webhook is ignored, an
enormous error message is truncated, a job is retried. Prevented *silently*,
each one teaches nobody anything - and when something finally does break, the
run-up to it is invisible.

Every prevented failure is reported here, in one shape, so that:

- it is greppable in the logs by a single token, ``ANOMALY``
- the set of things that can be reported is enumerable (see ``Anomaly``)
- there is one place to attach the operational view to, later, rather than
  thirty scattered ``logger.warning`` calls with thirty different formats

**Reporting is not an error path.** It must never raise, never change what the
caller does, and never fail the operation being performed. Something that
should stop the operation is an exception, not an anomaly.

Each name here should also appear in ``docs/limits.md``, which explains what the
failure looks like from outside and what to do about it.
"""

import logging
from typing import Any

logger = logging.getLogger("hba.anomaly")


class Anomaly:
    """The catalogue of prevented failures.

    A name is added here *with* an entry in docs/limits.md. A log line nobody
    can look up is only marginally better than no log line.
    """

    #: A webhook arrived twice under the same id but with different content.
    #: Deduplication ignored the second, which is right, but the two bodies
    #: disagreeing means one of our assumptions about the sender is wrong.
    EVENT_CONTENT_CHANGED = "event_content_changed"

    #: An error message exceeded the column and was cut down. The failure is
    #: still recorded; part of the detail is not.
    ERROR_TRUNCATED = "error_truncated"

    #: A job exhausted its retries. The work did not happen and will not be
    #: attempted again without someone acting.
    JOB_GAVE_UP = "job_gave_up"

    #: A job was found with an expired lease - the worker holding it died
    #: mid-flight. Reclaiming is normal; a lot of reclaiming is not.
    LEASE_RECLAIMED = "lease_reclaimed"

    #: A job was queued for a kind nothing knows how to handle. Usually a
    #: half-finished deploy: something queues work the running code cannot do.
    NO_HANDLER = "no_handler"

    #: The worker loop itself failed - not a job failing, which is normal, but
    #: the queue being unreachable. The worker survives and retries.
    WORKER_ITERATION_FAILED = "worker_iteration_failed"

    #: A webhook failed signature verification and was refused. Nothing is
    #: recorded for it, so this log line is the only trace it ever existed.
    WEBHOOK_REJECTED = "webhook_rejected"

    #: A webhook verified and was recorded, but nothing could be done with it -
    #: an order topic whose payload does not name an order.
    WEBHOOK_UNUSABLE = "webhook_unusable"

    #: We asked Shopify for an order and it has no such order. Normal for a
    #: deleted one; the answer to "why is this order not on the dashboard?".
    ORDER_NOT_FOUND = "order_not_found"

    #: Lines in a bulk export that could not be read or understood. The rest
    #: of the import went ahead; these orders are simply not in it.
    IMPORT_LINE_SKIPPED = "import_line_skipped"

    #: A bulk import finished having matched no orders at all.
    IMPORT_EMPTY = "import_empty"

    #: A reconciliation sweep stopped before reading the whole window, so the
    #: tail of it went unchecked this time round.
    RECONCILE_TRUNCATED = "reconcile_truncated"

    #: The worker could not queue its recurring work. Ordinary jobs still run;
    #: the reconciliation sweep and the prune do not until this clears.
    SCHEDULE_TOP_UP_FAILED = "schedule_top_up_failed"

    #: A Shopify fulfilment carried a display status nothing has classified.
    #: Treated as still in flight - it never earns and never voids on a guess -
    #: which means an unrecognised status would otherwise park an order for
    #: ever in silence.
    UNKNOWN_FULFILMENT_STATUS = "unknown_fulfilment_status"

    #: Work was queued for something already queued, and was absorbed.
    #: Expected in ordinary operation; a flood of it means a sender is looping.
    WORK_DEDUPLICATED = "work_deduplicated"


def report(anomaly: str, **context: Any) -> None:
    """Record that something was prevented. Never raises.

    Emits one line per occurrence:

        ANOMALY event_content_changed source=shopify external_id=evt-3

    Context values are rendered with ``repr`` so an empty string or a None is
    distinguishable from a missing key. **Never pass a credential, a token or a
    customer's details** - this goes to the log, which is not a private place.
    """
    try:
        detail = " ".join(f"{key}={value!r}" for key, value in sorted(context.items()))
        logger.warning("ANOMALY %s %s", anomaly, detail)
    except Exception:  # pragma: no cover - reporting must never break a caller
        logger.warning("ANOMALY %s <context unrenderable>", anomaly)
