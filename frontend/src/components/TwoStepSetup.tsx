import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { twoStep } from "../lib/api";
import type { TwoStepStart } from "../lib/api";
import { PasswordField } from "./PasswordField";
import "./TwoStepSetup.css";

const problemWords = (caught: unknown, fallback: string) =>
  caught instanceof Error ? caught.message : fallback;

/** A secret, in groups of four so it can be typed by eye. */
export function groupedInFours(secret: string): string {
  return (secret.replace(/\s+/g, "").match(/.{1,4}/g) ?? []).join(" ");
}

/** The server's QR as an image: it is shown, never inserted as markup. */
const imageOf = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

/** Copy text, and say so either way. */
function CopyButton({ text, label, done }: { text: string; label: string; done?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "refused">("idle");
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("refused");
    }
  }
  return (
    <button type="button" className="button button--row" onClick={copy}>
      {state === "copied" ? (done ?? "Copied") : state === "refused" ? "Could not copy - select it instead" : label}
    </button>
  );
}

/**
 * One code field and a button, for every place a code is asked: setting up,
 * new recovery codes, turning off, the owner resetting somebody else's.
 * The caller does the work; a refusal is shown here, in words.
 */
export function CodeForm({
  label = "6-digit code",
  hint,
  action,
  danger = false,
  onSubmit,
  onCancel,
  autoFocus = true,
}: {
  label?: string;
  hint?: string;
  action: string;
  danger?: boolean;
  onSubmit: (code: string) => Promise<void>;
  onCancel?: () => void;
  autoFocus?: boolean;
}) {
  const [code, setCode] = useState("");
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setProblem(null);
    try {
      await onSubmit(code.trim());
    } catch (caught) {
      setProblem(problemWords(caught, "That did not go through."));
      setWorking(false);
    }
  }

  return (
    <form className="twostep__form" onSubmit={submit}>
      <label className="field">
        <span className="field__label">{label}</span>
        <input
          className="input twostep__code"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus={autoFocus}
          required
          value={code}
          aria-describedby={hint ? "twostep-hint" : undefined}
          onChange={(event) => setCode(event.target.value)}
        />
      </label>
      {hint && <p id="twostep-hint" className="twostep__hint">{hint}</p>}
      {problem && <p className="notice notice--refused" role="alert">{problem}</p>}
      <div className="twostep__acts">
        {onCancel && (
          <button type="button" className="button" onClick={onCancel} disabled={working}>Cancel</button>
        )}
        <button
          type="submit"
          className={danger ? "button lifecycle__danger" : "button button--primary"}
          disabled={working || code.trim() === ""}
        >
          {working ? "Working…" : action}
        </button>
      </div>
    </form>
  );
}

/**
 * The ten recovery codes, shown once. They live in this component's state and
 * nowhere else; finishing hands control back and they are gone.
 */
export function RecoveryCodes({ codes, onSaved }: { codes: string[]; onSaved: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, []);
  return (
    <section className="twostep__step" aria-labelledby="recovery-title">
      <h2 id="recovery-title" className="twostep__title" tabIndex={-1} ref={headingRef}>Your recovery codes</h2>
      <p className="twostep__lead">
        Keep these somewhere safe. Each one works once, if you lose your phone. They are shown only now.
      </p>
      <ul className="twostep__codes" aria-label="Recovery codes">
        {codes.map((code) => <li key={code}><code>{code}</code></li>)}
      </ul>
      <div className="twostep__acts">
        <CopyButton text={codes.join("\n")} label="Copy all codes" done="Copied all codes" />
        <button type="button" className="button button--primary" onClick={onSaved}>I&apos;ve saved these</button>
      </div>
    </section>
  );
}

/**
 * Setting two-step sign-in up: the QR and the secret, one code to confirm,
 * then the recovery codes. One component for the forced screen and Settings.
 */
export function TwoStepSetup({ onDone, onCancel }: { onDone: () => void; onCancel?: () => void }) {
  const [start, setStart] = useState<TwoStepStart | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState(false);

  async function begin(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setProblem(null);
    try {
      setStart(await twoStep.start(password));
    } catch (caught) {
      setProblem(problemWords(caught, "Could not start set-up."));
    } finally {
      // Not kept: it was only for this one call.
      setPassword("");
      setWorking(false);
    }
  }

  if (codes) {
    return (
      <RecoveryCodes
        codes={codes}
        onSaved={() => {
          // Not kept: the codes are never shown again.
          setCodes(null);
          onDone();
        }}
      />
    );
  }

  return (
    <section className="twostep__step" aria-labelledby="scan-title">
      <h2 id="scan-title" className="twostep__title">{start ? "Add it to your authenticator app" : "Confirm it is you"}</h2>
      {problem && <p className="notice notice--refused" role="alert">{problem}</p>}
      {!start && (
        <form className="twostep__form" onSubmit={begin}>
          <p className="twostep__lead">Enter your password to set up two-step sign-in.</p>
          <PasswordField value={password} onChange={setPassword} advise={false} />
          <div className="twostep__acts">
            {onCancel && <button type="button" className="button" onClick={onCancel} disabled={working}>Cancel</button>}
            <button type="submit" className="button button--primary" disabled={working || password === ""}>
              {working ? "Checking…" : "Continue"}
            </button>
          </div>
        </form>
      )}
      {start && (
        <>
          <p className="twostep__lead">
            Scan this with an authenticator app, or type the key in by hand. Then enter the 6-digit code the app shows.
          </p>
          <img
            className="twostep__qr"
            src={imageOf(start.qr_svg)}
            alt="QR code for your authenticator app"
            width={200}
            height={200}
          />
          <div className="twostep__secret">
            <span className="twostep__secret-label">Key</span>
            <code aria-label="Setup key">{groupedInFours(start.secret)}</code>
            <CopyButton text={start.secret.replace(/\s+/g, "")} label="Copy key" />
          </div>
          <CodeForm
            action="Turn on"
            onCancel={onCancel}
            onSubmit={async (code) => {
              const result = await twoStep.confirm(code);
              setCodes(result.recovery_codes);
            }}
          />
        </>
      )}
    </section>
  );
}
