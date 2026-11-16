import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { ArrivalRow, DeliveryRow } from "./IncomingRows";
import { figures, summaryLine } from "./incomingLogic";
import type { Powers } from "./logic";
import type { Incoming } from "./types";
import { Problem, useIsNarrow } from "./ui";

/** `/production/incoming`: what is still to arrive at Khazenly, and every delivery with its two counts. */
export function IncomingScreen({ session }: { session: Session }) {
  const powers = useMemo<Powers>(
    () => ({ canEdit: can(session, "production.edit"), isOwner: can(session, "production.owner") }),
    [session],
  );
  const narrow = useIsNarrow();
  const [data, setData] = useState<Incoming | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Which answer is the newest: an answer that an earlier request delivers late, or one for a screen
  // that has been left, is dropped.
  const latest = useRef(0);

  const load = useCallback(() => {
    const mine = ++latest.current;
    setError(null);
    api.get<Incoming>("/api/prod/incoming")
      .then((answer) => {
        if (latest.current !== mine) return;
        setData(answer);
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "Incoming could not be loaded.");
      });
  }, []);

  useEffect(() => {
    load();
    return () => {
      latest.current += 1;
    };
  }, [load]);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Incoming</h1>
          <span className="page__subtitle">{data ? summaryLine(data.totals) : "Loading"}</span>
        </div>
      </div>

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!error && data === null && <p className="loading" role="status">Loading incoming…</p>}

      {data && (
        <>
          <dl className="prod-facts">
            {figures(data.totals).map((figure) => (
              <div key={figure.label}>
                <dt>{figure.label}</dt>
                <dd className={figure.tone ? `prod-${figure.tone}` : undefined}>{figure.value}</dd>
              </div>
            ))}
          </dl>

          <section aria-labelledby="prod-incoming-arrivals">
            <h2 id="prod-incoming-arrivals" className="prod-group">Arriving next</h2>
            {data.arrivals.length === 0 ? (
              <p className="empty">Nothing is on its way.</p>
            ) : (
              <ul className="surface prod-tasks">
                {data.arrivals.map((row) => (
                  <ArrivalRow key={row.key} row={row} powers={powers} narrow={narrow} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="prod-incoming-deliveries">
            <h2 id="prod-incoming-deliveries" className="prod-group">Deliveries</h2>
            {data.deliveries.length === 0 ? (
              <p className="empty">No deliveries yet.</p>
            ) : (
              <ul className="surface prod-tasks">
                {data.deliveries.map((row) => (
                  <DeliveryRow key={row.id} row={row} powers={powers} narrow={narrow} />
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </>
  );
}
