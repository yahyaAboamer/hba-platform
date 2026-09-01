import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PolicyText } from "../components/PolicyText";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";

type Policy = {
  id: number;
  effective_month: string;
  summary_markdown: string;
};

/**
 * The rules a settled month names, in full.
 *
 * §16, Phase 10 Batch C. Reached from a settled month's own figure - "the
 * rules in force since September 2026" links here rather than stating the
 * text inline, because most months somebody never needs to read it and the
 * figure should not compete with a page of prose for the same space.
 */
export function MyPolicy() {
  const { id = "" } = useParams();
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Policy>(`/api/me/policy/${id}`)
      .then(setPolicy)
      .catch((caught) => setError(caught.message));
  }, [id]);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (policy === null) return <p className="empty">Loading…</p>;

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <Link to="/" className="detail__back">
            Back
          </Link>
          <h1>The rules, since {formatMonth(policy.effective_month)}</h1>
        </div>
      </div>

      <section className="panel">
        <PolicyText markdown={policy.summary_markdown} />
      </section>
    </>
  );
}
