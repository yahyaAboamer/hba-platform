import { useCallback, useEffect, useState } from "react";

import { MonthPicker } from "../../components/MonthPicker";
import { PolicyText } from "../../components/PolicyText";
import { api } from "../../lib/api";
import { ActivityPanel } from "./ActivityPanel";
import type { Session } from "../../lib/api";
import { currentMonth, formatMonth, monthAdd, monthsBetween } from "../../lib/money";
import "../Settings.css";

// ── Pay policy ────────────────────────────────────────────────────────────

type PolicyVersionRow = {
  id: number;
  effective_month: string;
  summary_markdown: string;
  created_at: string;
};

/**
 * §16, Phase 10 Batch C. The commission rules in the words a model reads -
 * linked from her own statement of each month.
 *
 * **A new version, never an edit.** Every payroll snapshot freezes which
 * version it was calculated under. The text is written beside a preview of
 * exactly what she will see (R5), because a policy written blind is how a
 * typo reaches twenty models.
 */
function PolicyPanel() {
  const [versions, setVersions] = useState<PolicyVersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [effectiveMonth, setEffectiveMonth] = useState(currentMonth());
  const [text, setText] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(() => {
    api.get<{ versions: PolicyVersionRow[] }>("/api/policy/versions")
      .then((body) => setVersions(body.versions)).catch((caught) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      await api.post("/api/policy/versions", { effective_month: effectiveMonth, summary_markdown: text });
      setText("");
      setAdding(false);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that.");
    } finally {
      setWorking(false);
    }
  }

  const now = currentMonth();
  const all = versions ?? [];
  const newest = all.length > 0 ? all[all.length - 1] : null;
  // The first month the server will take: this one, or the month after the
  // newest version when that is already this month or later. The picker
  // offered earlier months the server then refused.
  const firstAllowed = newest && newest.effective_month >= now ? monthAdd(newest.effective_month, 1) : now;
  const inForce = [...all].reverse().find((version) => version.effective_month <= now) ?? null;
  const upcoming = all.filter((version) => version.effective_month > now);
  const earlier = all.filter((version) => version !== inForce && version.effective_month <= now).reverse();

  return (
    <>
      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">Pay policy</h2>
          <span className="settings__head-note">What every model reads about her pay</span>
        </div>
        <div className="settings__pad">
          {error && <p className="notice notice--refused" role="alert">{error}</p>}
          {versions === null ? <p className="empty">Loading…</p> : all.length === 0 ? (
            <p className="settings__note">
              None written yet. Every settled month shows that no rules were in
              force - add the first version below.
            </p>
          ) : <>
            {upcoming.map((version) => (
              <PolicyCard key={version.id} version={version} tag={`Starts ${formatMonth(version.effective_month)}`} tone="owed" />
            ))}
            {inForce && <PolicyCard version={inForce} tag={`In force from ${formatMonth(inForce.effective_month)}`} tone="ok" />}
            {earlier.length > 0 && (
              <details className="settings__earlier">
                <summary>Earlier versions ({earlier.length})</summary>
                {earlier.map((version) => (
                  <PolicyCard key={version.id} version={version} tag={`From ${formatMonth(version.effective_month)}`} tone="off" />
                ))}
              </details>
            )}
          </>}
          {!adding && (
            <button type="button" className="button settings__policy-add" onClick={() => { setAdding(true); setEffectiveMonth(firstAllowed); }}>
              Write a new version
            </button>
          )}
        </div>
      </section>

      {adding && (
        <section className="panel">
          <form onSubmit={submit}>
            <div className="panel__head">
              <h2 className="panel__title">New version</h2>
              <label className="settings__head-note settings__inline-field">
                From
                {/* From this month (or the newest version's, if later) to the
                 *  end of next year; the server still decides what may be saved. */}
                <MonthPicker value={effectiveMonth} onChange={setEffectiveMonth} size="section" label={false}
                  months={monthsBetween(firstAllowed, `${Number(now.slice(0, 4)) + 1}-12`)} />
              </label>
            </div>
            <div className="settings__pad">
              <p className="settings__note">
                {newest
                  ? `Must start later than ${formatMonth(newest.effective_month)}. Months already agreed keep the words they were agreed under.`
                  : "Every month from here onward reads this version."}
              </p>
              <div className="settings__split">
                <label className="field">
                  <span className="field__label">The text</span>
                  <textarea className="input settings__policy-text" rows={12} required value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder={"## How commission works\n\nCommission is worked out on..."} />
                  <span className="field__hint">`## ` starts a heading and `**text**` is bold - nothing else is read specially.</span>
                </label>
                <div className="field">
                  <span className="field__label">What a model will see</span>
                  <div className="settings__preview">
                    {text.trim() ? <PolicyText markdown={text} /> : <p className="settings__muted">The preview appears as you type.</p>}
                  </div>
                </div>
              </div>
              <div className="settings__acts">
                <button type="button" className="button" onClick={() => { setAdding(false); setError(null); }} disabled={working}>Cancel</button>
                <button type="submit" className="button button--primary" disabled={working || !text.trim()}>
                  {working ? "Saving…" : "Save this version"}
                </button>
              </div>
            </div>
          </form>
        </section>
      )}
    </>
  );
}

function PolicyCard({ version, tag, tone }: { version: PolicyVersionRow; tag: string; tone: string }) {
  return (
    <article className="settings__policy">
      <span className={`pill settings__pill--${tone}`}>{tag}</span>
      <PolicyText markdown={version.summary_markdown} />
    </article>
  );
}


function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="settings__fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** `/settings/company`: the pay policy, the go-live month, and the whole activity log. The owner's. */
export function Company({ session }: { session: Session }) {
  const goLive = session.platform.go_live_month;
  return <>
    <div className="page__head"><div className="page__title"><h1>Company</h1></div></div>
    <div className="settings__sections">
      <PolicyPanel />
      <section className="panel">
        <div className="panel__head"><h2 className="panel__title">Go-live</h2></div>
        <dl className="settings__facts">
          <Row label="Go-live month">{goLive ? formatMonth(goLive) : "Not set"}</Row>
        </dl>
      </section>
      <ActivityPanel title="Activity log" />
    </div>
  </>;
}
