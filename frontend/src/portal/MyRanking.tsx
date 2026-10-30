import { useEffect, useState } from "react";

import { usePortal } from "./AffiliateLayout";
import { Money } from "../components/Money";
import { PortalSkeleton } from "./PortalSkeleton";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import "./MyRanking.css";

type Row = {
  affiliate_id: number;
  rank: number;
  name: string | null;
  is_me: boolean;
  /** The API withholds peers' figures; only her own use count is returned. */
  uses: number | null;
  sales_piastres: number | null;
};

type Board = { month: string; basis: string; rows: Row[] };

/** Sales decide position; code uses only break ties (M02, D03). */
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
  if (!board) return <PortalSkeleton screen="ranking" />;

  return <RankingContents key={board.month} board={board} />;
}

/** Her figures and the complete order of models, without peers' figures. */
export function RankingContents({ board }: { board: Board }) {
  const mine = board.rows.find((row) => row.is_me);

  const shared = mine
    ? board.rows.filter((row) => row.rank === mine.rank).length > 1
    : false;

  return (
    <div className="ranking">
      <div className="ranking__head">
        <h1>Ranking</h1>
        <span>{formatMonth(board.month)}</span>
      </div>

      {mine && (
        <section className="ranking__mine">
          <div className="ranking__top">
            <div>
              <span className="ranking__caption">Your position</span>
              <span className="ranking__number">{ordinal(mine.rank)}</span>
            </div>
            <div className="ranking__side">
              <span className="ranking__sales">{mine.sales_piastres === null ? "Sales unavailable" : <Money piastres={mine.sales_piastres} />}</span>
              <span className="ranking__caption">
                Your code sales · {mine.uses ?? "—"} {mine.uses === 1 ? "use" : "uses"}
              </span>
            </div>
          </div>
          <div className="ranking__basis">
            <strong>Sales decide the order.</strong> Code uses break ties. Only your sales and uses are shown.
            {shared && <p>You are level with somebody this month, so you share a place.</p>}
          </div>
        </section>
      )}

      {!mine && <p className="ranking__unranked">You are not ranked this month yet.</p>}
      <section className="ranking__group">
        <div className="ranking__group-head"><h2>All models</h2><span>{formatMonth(board.month)}</span></div>
        {board.rows.length ? <RankingRows rows={board.rows} /> : <p className="empty">No models ranked this month yet.</p>}
      </section>
      <p className="ranking__foot">Equal sales and equal uses share a place.</p>
    </div>
  );
}

function RankingRows({ rows }: { rows: Row[] }) {
  return <ul className="ranking__board">
    {rows.map((row) => (
      <li key={row.affiliate_id} className={row.is_me ? "ranking__row ranking__row--me" : "ranking__row"}>
        <span className="ranking__rank">{row.rank}</span>
        <span className="ranking__avatar">{(row.name ?? "").trim().charAt(0).toUpperCase() || "·"}</span>
        <span className="ranking__who">
          <span className="ranking__name">{row.is_me ? "You" : row.name ?? "Model"}</span>
        </span>
      </li>
    ))}
  </ul>;
}

function ordinal(place: number): string {
  const tens = place % 100;
  if (tens >= 11 && tens <= 13) return `${place}th`;
  return `${place}${["th", "st", "nd", "rd"][place % 10] ?? "th"}`;
}
