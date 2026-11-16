import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  arrivalDue,
  arrivalOrderLine,
  arrivalSizes,
  arrivalTitle,
  deliveryButton,
  deliveryLine,
  deliveryPill,
  deliveryTitle,
  orderAddress,
  recordLink,
} from "./incomingLogic";
import type { Powers } from "./logic";
import type { IncomingArrival, IncomingDelivery } from "./types";

type RowProps<T> = { row: T; powers: Powers; narrow: boolean };

/** One row's frame: the text, then what sits beside it on a wide screen or below it on a phone. */
function Frame({ narrow, what, side }: { narrow: boolean; what: ReactNode; side: ReactNode }) {
  return narrow ? (
    <li className="prod-task prod-task--narrow">
      <div>{what}</div>
      <div className="prod-task__actions">{side}</div>
    </li>
  ) : (
    <li className="prod-task">
      <div className="prod-task__what">{what}</div>
      <div className="prod-task__side">{side}</div>
    </li>
  );
}

/** One piece of work still to arrive: what, the sizes, where it stands, when, and "Record delivery". */
export function ArrivalRow({ row, powers, narrow }: RowProps<IncomingArrival>) {
  const title = arrivalTitle(row);
  const record = recordLink(row, powers);
  const sizes = arrivalSizes(row);
  return (
    <Frame
      narrow={narrow}
      what={
        <>
          <b>
            <Link className="prod-rowlink" to={orderAddress(row.order.id)}>
              {title}
            </Link>
          </b>
          {sizes && <div className="prod-small">{sizes}</div>}
          <div className="prod-small">{arrivalOrderLine(row)}</div>
        </>
      }
      side={
        <>
          <span className={row.late_days > 0 ? "prod-late" : undefined}>{arrivalDue(row)}</span>
          {record && (
            <Link className="button button--row" to={record} aria-label={`Record delivery: ${title}`}>
              Record delivery
            </Link>
          )}
        </>
      }
    />
  );
}

/** One delivery: what left the factory, what Khazenly counted, the state in words, and the next step. */
export function DeliveryRow({ row, powers, narrow }: RowProps<IncomingDelivery>) {
  const title = deliveryTitle(row);
  const pill = deliveryPill(row);
  const button = deliveryButton(row, powers);
  return (
    <Frame
      narrow={narrow}
      what={
        <>
          <b>
            <Link className="prod-rowlink" to={orderAddress(row.order.id)}>
              {title}
            </Link>
          </b>
          <div className="prod-small">{deliveryLine(row)}</div>
          {row.state === "explained" && row.reason && <div className="prod-small prod-task__note">Reason given: {row.reason}</div>}
        </>
      }
      side={
        <>
          <span className={`prod-pill${pill.tone ? ` prod-pill--${pill.tone}` : ""}`}>{pill.text}</span>
          {button && (
            <Link className="button button--row" to={button.to} aria-label={`${button.label}: ${title}`}>
              {button.label}
            </Link>
          )}
        </>
      }
    />
  );
}
