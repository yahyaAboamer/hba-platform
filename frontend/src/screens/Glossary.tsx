import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { GLOSSARY_TERMS } from "../lib/glossary";
import "./Glossary.css";

/**
 * The words this platform uses, defined once.
 *
 * §16, Phase 10 Batch C. One page for the maintainer and a model alike - the
 * definitions do not differ by who is reading, and two glossaries are two
 * things that can quietly disagree. Reached from an ⓘ beside a term
 * wherever one already appears; this is not a replacement for those inline
 * explanations, only where somebody goes when one is not enough.
 *
 * A term in the URL's hash (`#void`) is highlighted and scrolled to, so a
 * link from elsewhere in the platform can point at the one word that sent
 * somebody here rather than the top of a list of eight.
 */
export function Glossary() {
  const { hash } = useLocation();
  const target = hash.replace("#", "");

  // React Router does not scroll to a hash on client-side navigation the way
  // a full page load does - without this, following a link from elsewhere in
  // the platform lands on the top of eight terms rather than the one that
  // was actually linked.
  useEffect(() => {
    if (!target) return;
    document.getElementById(target)?.scrollIntoView({ block: "start" });
  }, [target]);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>What these words mean</h1>
        </div>
      </div>

      <section className="panel">
        <dl className="glossary__list">
          {GLOSSARY_TERMS.map((entry) => (
            <div
              key={entry.id}
              id={entry.id}
              className={
                entry.id === target
                  ? "glossary__entry glossary__entry--target"
                  : "glossary__entry"
              }
            >
              <dt>{entry.term}</dt>
              <dd>{entry.definition}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
