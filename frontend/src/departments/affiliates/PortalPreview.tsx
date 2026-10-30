import { useEffect, useState } from "react";
import { Link, MemoryRouter, useParams } from "react-router-dom";

import { api, startPortalPreview } from "../../lib/api";
import type { Session } from "../../lib/api";
import { AffiliatePortal } from "../../portal/AffiliatePortal";
import "./PortalPreview.css";

/**
 * A model's portal, as staff may look at it: her screens and her figures,
 * read only (ADR 0064).
 *
 * **Her portal runs in a frame**, not on this page. A frame is a real
 * viewport, so at phone width her phone layout is what renders - a narrow box
 * on a desktop page would still be laid out for a desktop. The frame is also
 * its own page, so the switch that sends her reads to the preview routes and
 * refuses every write (`startPortalPreview`) cannot reach the admin around it.
 */

type Size = "phone" | "full";
const SIZE_KEY = "hba.portal-preview.size";

function storedSize(): Size {
  try {
    return localStorage.getItem(SIZE_KEY) === "full" ? "full" : "phone";
  } catch {
    // Private windows throw on access; the phone is the default anyway.
    return "phone";
  }
}

/** The address of the frame itself, for `App` to recognise before routing. */
export function previewFrameFor(pathname: string): number | null {
  const found = /^\/affiliates\/(\d+)\/portal\/frame\/?$/.exec(pathname);
  return found ? Number(found[1]) : null;
}

export function PortalPreview() {
  const { id } = useParams();
  const [name, setName] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [size, setSize] = useState<Size>(storedSize);

  useEffect(() => {
    let current = true;
    api
      .get<{ name: string }>(`/api/affiliates/${id}`)
      .then((body) => current && setName(body.name))
      .catch((caught) => current && setProblem(caught.message));
    return () => {
      current = false;
    };
  }, [id]);

  function pick(next: Size) {
    setSize(next);
    try {
      localStorage.setItem(SIZE_KEY, next);
    } catch {
      /* see storedSize */
    }
  }

  if (problem) {
    return (
      <p className="notice notice--refused" role="alert">
        {problem}
      </p>
    );
  }

  const who = name ?? "Her";

  return (
    <>
      <div className="page__head">
        <Link className="button profile__back" to={`/affiliates/${id}`}>
          ← {name ?? "Back"}
        </Link>
        <div className="page__title">
          <h1>{name ? `${name}'s portal` : "Her portal"}</h1>
          <span className="page__subtitle">
            What she sees, with her real figures · read only
          </span>
        </div>
        <div className="seg" role="radiogroup" aria-label="Preview size">
          <label className="seg-opt">
            <input
              type="radio"
              name="preview-size"
              checked={size === "phone"}
              onChange={() => pick("phone")}
            />
            Phone
          </label>
          <label className="seg-opt">
            <input
              type="radio"
              name="preview-size"
              checked={size === "full"}
              onChange={() => pick("full")}
            />
            Full width
          </label>
        </div>
      </div>

      <p className="preview__note">
        Nothing can be changed here. The buttons she uses to edit her details,
        payment method and notifications are hidden, and her payment details
        stay shortened.
      </p>

      <div className={`preview__stage preview__stage--${size}`}>
        <iframe
          className="preview__frame"
          src={`/affiliates/${id}/portal/frame`}
          title={`${who}'s portal, read only`}
        />
      </div>
    </>
  );
}

/**
 * Inside the frame: her portal, with every read sent to the preview routes.
 *
 * Its own router in memory, because her portal's addresses (`/`, `/earnings`,
 * `/you`) are the admin's addresses too; in the frame's address bar they would
 * open admin screens.
 */
export function PortalPreviewFrame({
  affiliateId,
  session,
}: {
  affiliateId: number;
  session: Session;
}) {
  // Before the first render, so her very first read already goes to the
  // preview - an effect would run after the portal had asked for `/api/me`.
  useState(() => startPortalPreview(affiliateId));

  let framed = true;
  try {
    framed = window.self !== window.top;
  } catch {
    /* A cross-origin parent: framed, then. */
  }

  return (
    <>
      {/* Opened on its own rather than inside the admin page, the frame says
          what it is itself. */}
      {!framed && (
        <p className="preview__strip" role="status">
          Read-only preview of her portal.{" "}
          <a href={`/affiliates/${affiliateId}`}>Back to her profile</a>
        </p>
      )}
      <MemoryRouter>
        <AffiliatePortal session={session} />
      </MemoryRouter>
    </>
  );
}
