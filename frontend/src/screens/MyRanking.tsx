import { useEffect, useState } from "react";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import "./MyRanking.css";

type Row = {
  affiliate_id: number;
  rank: number;
  name: string | null;
  is_me: boolean;
  uses: number;
  sales_piastres: number | null;
};

type Board = { month: string; basis: string; rows: Row[] };

/**
 * Where she stands, and what the order is actually decided on.
 *
 * ## Two different numbers, on purpose
 *
 * M02: the board is **ordered by sales**, and the figure shown against every
 * other model is her **uses** — never their sales, commission or salary. So
 * the column somebody reads is not the column the order is made from, and that
 * has to be said rather than left to be discovered.
 *
 * It matters because uses only break a *tie*. Two models can show the same use
 * count and sit in different places, and a screen that implied matching
 * somebody's uses would match her rank would be making a promise the rule does
 * not keep — which is exactly what M02 warns against.
 *
 * ## Nobody else is named
 *
 * A rank and a use count, and her own row is the only one with a name on it. A
 * leaderboard that names everybody turns twenty colleagues into a public
 * table, and none of them agreed to that.
 *
 * ## Equal standings share a place (D03)
 *
 * Two models level on both figures are both first, and the next is third —
 * because two places have been used up. The jump is not a missing row.
 */
export function MyRanking() {
  const { month } = usePortal();
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!month) return;
    let live = true;
    setBoard(null);
    setError(null);
    api
      .get<Board>(`/api/me/ranking/${month}`)
      .then((body) => {
        if (live) setBoard(body);
      })
      .catch((caught) => {
        // Never rendered as an empty board (§S06): "nobody has any sales" and
        // "the request failed" are different facts.
        if (live) setError(caught.message);
      });
    return () => {
      live = false;
    };
  }, [month]);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (!board) return <p className="empty">Loading…</p>;

  const mine = board.rows.find((row) => row.is_me);
  const shared = mine
    ? board.rows.filter((row) => row.rank === mine.rank).length > 1
    : false;

  return (
    <div className="ranking">
      {mine && (
        <section className="panel ranking__mine">
          <div className="ranking__place">
            <span className="ranking__number">{ordinal(mine.rank)}</span>
            <span className="ranking__of">
              of {board.rows.length} for {formatMonth(board.month)}
            </span>
          </div>
          <p className="ranking__figures">
            <Money piastres={mine.sales_piastres ?? 0} /> of sales ·{" "}
            {mine.uses} {mine.uses === 1 ? "use" : "uses"} of your code
          </p>
          {/*
           * Said once, plainly, because the column below is uses and the order
           * is not. Without this the board looks wrong to anybody who reads
           * down it and finds a smaller number above a bigger one.
           */}
          <p className="ranking__basis">
            Places are decided by sales. The number beside each place is how
            many times that model&rsquo;s code was used — it settles a tie, so
            the same number of uses does not always mean the same place.
          </p>
          {shared && (
            <p className="ranking__basis">
              You are level with somebody this month, so you share a place.
            </p>
          )}
        </section>
      )}

      <section className="panel">
        <ul className="ranking__board">
          {board.rows.map((row, index) => (
            <li
              key={row.affiliate_id}
              className={row.is_me ? "ranking__row ranking__row--me" : "ranking__row"}
            >
              {/*
               * The place is printed only when it changes going down the list,
               * so two models sharing first read as one place with two models
               * in it rather than as the same number written twice.
               */}
              <span className="ranking__rank">
                {index > 0 && board.rows[index - 1].rank === row.rank
                  ? ""
                  : ordinal(row.rank)}
              </span>
              <span className="ranking__who">
                {row.is_me ? row.name ?? "You" : "Another model"}
              </span>
              <span className="code ranking__uses">{row.uses}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ordinal(place: number): string {
  const tens = place % 100;
  if (tens >= 11 && tens <= 13) return `${place}th`;
  return `${place}${["th", "st", "nd", "rd"][place % 10] ?? "th"}`;
}
