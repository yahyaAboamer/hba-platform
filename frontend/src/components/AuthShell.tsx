import type { FormEvent, ReactNode } from "react";

import { storedTheme } from "../lib/theme";
import "../screens/SignIn.css";

/**
 * The frame every sign-in-shaped screen shares: signing in, accepting an
 * invitation, resetting a password, setting up the platform, and a model's
 * application.
 *
 * **The portal's look, for everyone** (ADR 0047). A model arrives here from
 * an email on her phone, and the screen before her dashboard used to be the
 * maintainer's light laptop form - it looked like somebody else's product.
 * The owner chose one look for the whole family rather than two, so staff
 * signing in see it too.
 *
 * **The device's portal theme**, dark unless she chose light. Nobody is signed
 * in yet, so there is no account to ask; the device is what remembers.
 *
 * `step` draws the two-segment bar that replaced *"we will ask for your
 * details next"*: a first-time model sees she is one of two steps in, without
 * a sentence telling her so.
 */
export function AuthShell({
  eyebrow,
  title,
  step,
  onSubmit,
  children,
}: {
  eyebrow?: string;
  title: string;
  step?: { current: number; of: number };
  onSubmit?: (event: FormEvent) => void;
  children: ReactNode;
}) {
  const head = (
    <div className="auth__head">
      {eyebrow && <span className="auth__eyebrow">{eyebrow}</span>}
      <h1 className="auth__title">{title}</h1>
    </div>
  );

  return (
    <main className="auth" data-theme={storedTheme("portal")}>
      <div className="auth__column">
        <div className="auth__top">
          <span className="auth__mark">HBA</span>
          {step && (
            <span
              className="auth__steps"
              role="img"
              aria-label={`Step ${step.current} of ${step.of}`}
            >
              {Array.from({ length: step.of }, (_, index) => (
                <span
                  key={index}
                  className={
                    index < step.current
                      ? "auth__step auth__step--done"
                      : "auth__step"
                  }
                />
              ))}
            </span>
          )}
        </div>

        {onSubmit ? (
          <form className="auth__body" onSubmit={onSubmit}>
            {head}
            {children}
          </form>
        ) : (
          <div className="auth__body">
            {head}
            {children}
          </div>
        )}
      </div>
    </main>
  );
}

/** Who this is for, as a chip - the invitation and the reset both name it. */
export function AccountChip({ email }: { email: string }) {
  return (
    <span className="auth__chip">
      <span className="auth__avatar" aria-hidden="true">
        {email.charAt(0).toUpperCase()}
      </span>
      <span className="auth__chip-text">{email}</span>
    </span>
  );
}
