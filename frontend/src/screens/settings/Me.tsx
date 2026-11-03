import { useCallback, useEffect, useState } from "react";

import { pickMaintainerChoice, storedMaintainerChoice, themePickedThisVisit } from "../../lib/theme";
import type { ThemeChoice } from "../../lib/theme";
import { api, devices, trustedBrowsers, twoStep } from "../../lib/api";
import type { DeviceSession, TrustedBrowser, TwoStepStatus } from "../../lib/api";
import { CodeForm, PasswordForm, RecoveryCodes, TwoStepSetup } from "../../components/TwoStepSetup";
import { BrowserLine, DeviceLine } from "./DeviceLines";
import "../Settings.css";

const THEME_WORDS: [ThemeChoice, string][] = [["dark", "Dark"], ["light", "Light"], ["system", "Match my device"]];

/**
 * The theme, saved on the account so it follows this person between devices
 * (P1). It paints at once and is put back if the server refuses.
 */
function AppearancePanel() {
  const [theme, setTheme] = useState<ThemeChoice>(() => storedMaintainerChoice());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // The account's choice is the one that holds. This device's copy can be a
  // step behind it on the first visit from a new laptop, and a radio that
  // shows the wrong side cannot be pressed back to the right one.
  useEffect(() => {
    let live = true;
    api.get<{ theme: ThemeChoice | null }>("/api/staff/me/preferences")
      .then((body) => { if (live && body.theme && !themePickedThisVisit()) setTheme(body.theme); })
      .catch(() => undefined);
    return () => { live = false; };
  }, []);

  async function choose(value: ThemeChoice) {
    if (saving) return;
    const before = theme;
    setTheme(value);
    pickMaintainerChoice(value);
    setError(null);
    setSaving(true);
    try {
      await api.put("/api/staff/me/theme", { theme: value });
    } catch (caught) {
      setTheme(before);
      pickMaintainerChoice(before);
      setError(`${caught instanceof Error ? caught.message : "Could not save that."} Nothing changed.`);
    } finally {
      setSaving(false);
    }
  }

  return <>
    <section className="panel settings__appearance">
      <span>Theme<small>Saved to your account, so it follows you to any device</small></span>
      <div className="seg" role="radiogroup" aria-label="Theme">{THEME_WORDS.map(([value, words]) =>
        <label key={value} className="seg-opt">
          <input type="radio" name="admin-theme" checked={theme === value} disabled={saving} onChange={() => choose(value)} />
          <span>{words}</span>
        </label>)}</div>
    </section>
    {error && <p className="notice notice--refused" role="alert">{error}</p>}
    <PreferenceSwitches />
    <TwoStepPanel />
    <DevicesPanel />
  </>;
}

/** `/settings/me`: what is only about the signed-in person. Every member of staff has it. */
export function Me() {
  return <>
    <div className="page__head"><div className="page__title"><h1>Me</h1></div></div>
    <div className="settings__sections"><AppearancePanel /></div>
  </>;
}

type TwoStepMode = "idle" | "setup" | "renew" | "off" | "codes" | "email";

/**
 * Two-step sign-in for the signed-in person, and which kind applies to them:
 * an authenticator app (the owner), a code by email (whoever approves or pays
 * money, or anybody who chooses it), or nothing. A new browser is asked; a
 * remembered one is not. Changing it asks for a code or the password, so a
 * borrowed laptop cannot.
 */
function TwoStepPanel() {
  const [status, setStatus] = useState<TwoStepStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<TwoStepMode>("idle");
  // Held only while they are on screen; cleared as soon as they are saved.
  const [codes, setCodes] = useState<string[] | null>(null);

  const load = useCallback(() => {
    twoStep.status().then(setStatus)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load this."));
  }, []);
  useEffect(load, [load]);

  const finish = () => { setCodes(null); setMode("idle"); load(); };

  // An older answer that says "required" and nothing more meant the owner's.
  const requiredMethod = status?.required ? (status.required_method ?? "authenticator") : null;
  const emailOn = status?.email_on ?? false;
  const anyOn = status ? (status.method != null || status.enabled || emailOn || requiredMethod === "email") : false;

  return (
    <section className="panel" aria-labelledby="twostep-title">
      <div className="panel__head">
        <h2 className="panel__title" id="twostep-title">Two-step sign-in</h2>
        {status && <span className={`pill ${anyOn ? "twostep__on" : "twostep__off"}`}>{anyOn ? "On" : "Off"}</span>}
      </div>
      <div className="twostep__panel-body">
        {error && <p className="notice notice--refused" role="alert">{error}</p>}
        {status && mode === "idle" && <>
          <p className="settings__explain-line">
            {requiredMethod
              ? <><b>Required for your access: a code {requiredMethod === "email" ? "by email" : "from an authenticator app"} on a new browser.</b>{" "}</>
              : "On a browser you have not used before, signing in asks for a code as well as your password. "}
            {status.enabled && `${status.recovery_codes_left} recovery ${status.recovery_codes_left === 1 ? "code" : "codes"} left.`}
          </p>

          {requiredMethod !== "authenticator" && (
            <div className="twostep__state">
              <button type="button" role="switch" aria-checked={emailOn || requiredMethod === "email"} aria-label="Code by email"
                disabled={requiredMethod === "email"} className="settings__switch twostep__switch"
                onClick={() => setMode("email")}>
                <span className="settings__switch-words">Code by email
                  <small>{requiredMethod === "email" ? "Required for your access" : "We email a 6-digit code to your address"}</small></span>
                <span className={`settings__track${emailOn || requiredMethod === "email" ? " settings__track--on" : ""}`} aria-hidden="true"><span /></span>
              </button>
            </div>
          )}

          <div className="twostep__state">
            <span>Authenticator app <small className="twostep__hint">{status.enabled ? "On" : "Off"}</small></span>
            <span className="twostep__acts">
              {!status.enabled && <button type="button" className="button" onClick={() => setMode("setup")}>Set up two-step sign-in</button>}
              {status.enabled && <button type="button" className="button" onClick={() => setMode("renew")}>New recovery codes</button>}
              {status.enabled && requiredMethod !== "authenticator" && <button type="button" className="button lifecycle__danger" onClick={() => setMode("off")}>Turn off</button>}
            </span>
          </div>
        </>}
        {mode === "email" && <PasswordForm
          lead={emailOn ? "Enter your password to stop getting codes by email." : "Enter your password to get a code by email on a new browser."}
          action={emailOn ? "Turn off" : "Turn on"}
          onCancel={() => setMode("idle")}
          onSubmit={async (password) => { await twoStep.setEmail(!emailOn, password); finish(); }} />}
        {mode === "setup" && <TwoStepSetup onDone={finish} onCancel={() => setMode("idle")} />}
        {mode === "renew" && <CodeForm
          label="6-digit code"
          hint="Your old recovery codes stop working."
          action="Make new recovery codes"
          onCancel={() => setMode("idle")}
          onSubmit={async (code) => { setCodes((await twoStep.newRecoveryCodes(code)).recovery_codes); setMode("codes"); }} />}
        {mode === "codes" && codes && <RecoveryCodes codes={codes} onSaved={finish} />}
        {mode === "off" && <CodeForm
          label="6-digit code"
          action="Turn off two-step sign-in"
          danger
          onCancel={() => setMode("idle")}
          onSubmit={async (code) => { await twoStep.turnOff(code); finish(); }} />}
      </div>
    </section>
  );
}

/** Where this account is signed in, with a way to end any of it. */
function DevicesPanel() {
  const [list, setList] = useState<DeviceSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<number | "others" | "browser" | null>(null);
  const [remembered, setRemembered] = useState<TrustedBrowser[]>([]);

  const load = useCallback(() => {
    trustedBrowsers.mine().then((body) => setRemembered(body.browsers)).catch(() => undefined);
    devices.mine().then((body) => setList(body.sessions))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load this."));
  }, []);
  useEffect(load, [load]);

  async function end(which: number | "others") {
    setWorking(which);
    setError(null);
    try {
      await (which === "others" ? devices.endOthers() : devices.endOne(which));
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That did not go through.");
    } finally {
      setWorking(null);
    }
  }

  async function forget(which: number | "all") {
    setWorking("browser");
    setError(null);
    try {
      await (which === "all" ? trustedBrowsers.forgetAll() : trustedBrowsers.forget(which));
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That did not go through.");
    } finally {
      setWorking(null);
    }
  }

  const others = (list ?? []).filter((device) => !device.current);
  return (
    <section className="panel" aria-labelledby="devices-title">
      <div className="panel__head"><h2 className="panel__title" id="devices-title">Signed in on</h2></div>
      {error && <p className="notice notice--refused" role="alert">{error}</p>}
      {list === null && !error && <p className="empty">Loading…</p>}
      {list && <ul className="settings__devices" aria-label="Devices">
        {list.map((device) => <DeviceLine key={device.id} device={device} action={device.current ? undefined :
          <button type="button" className="button button--row" disabled={working !== null}
            aria-label={`Sign out ${device.device}`} onClick={() => end(device.id)}>Sign out</button>} />)}
      </ul>}
      {others.length > 0 && <div className="twostep__panel-body">
        <div className="twostep__acts">
          <button type="button" className="button" disabled={working !== null} onClick={() => end("others")}>
            Sign out of every other device
          </button>
        </div>
      </div>}
      {remembered.length > 0 && <>
        <h3 className="twostep__sub">Remembered browsers</h3>
        <ul className="settings__devices" aria-label="Remembered browsers">
          {remembered.map((browser) => <BrowserLine key={browser.id} browser={browser} action={
            <button type="button" className="button button--row" disabled={working !== null}
              aria-label={`Forget ${browser.device}`} onClick={() => forget(browser.id)}>Forget</button>} />)}
        </ul>
        <div className="twostep__panel-body">
          <div className="twostep__acts">
            <button type="button" className="button" disabled={working !== null} onClick={() => forget("all")}>
              Forget every browser
            </button>
          </div>
        </div>
      </>}
    </section>
  );
}

type Preferences = {
  preferences: Record<string, boolean>;
  labels: Record<string, string>;
  /** One line under each switch saying what it does (P2). */
  descriptions?: Record<string, string>;
  theme?: ThemeChoice | null;
};

/**
 * The export's two switches (`prefRows`, Admin lines 749-757), **saved on the
 * server for this account**, so they hold after a reload and on another
 * device. A switch moves when the server has said so, not before; a refusal
 * leaves it where it was and says why.
 */
export function PreferenceSwitches() {
  const [body, setBody] = useState<Preferences | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    api.get<Preferences>("/api/staff/me/preferences").then(setBody)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load these."));
  }, []);

  async function toggle(key: string) {
    if (!body) return;
    setSaving(key);
    setError(null);
    try {
      setBody(await api.put<Preferences>("/api/staff/me/preferences", { key, enabled: !body.preferences[key] }));
    } catch (caught) {
      setError(`${caught instanceof Error ? caught.message : "Could not save that."} Nothing changed.`);
    } finally {
      setSaving(null);
    }
  }

  return <>
    {body && <div className="settings__switches">
      {Object.entries(body.labels).map(([key, label]) => {
        const on = body.preferences[key];
        const hint = body.descriptions?.[key];
        return <button key={key} type="button" role="switch" aria-checked={on} aria-label={label} disabled={saving === key}
          className="settings__switch" onClick={() => toggle(key)}>
          <span className="settings__switch-words">{label}{hint && <small>{hint}</small>}</span>
          <span className={`settings__track${on ? " settings__track--on" : ""}`} aria-hidden="true"><span /></span>
        </button>;
      })}
    </div>}
    {error && <p className="notice notice--refused settings__switch-error" role="alert">{error}</p>}
  </>;
}

