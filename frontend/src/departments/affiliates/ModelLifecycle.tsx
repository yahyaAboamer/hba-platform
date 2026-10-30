import { useEffect, useRef, useState } from "react";

import { api, can, type Session } from "../lib/api";
import "./ModelLifecycle.css";

/**
 * A model's life, from her profile (ADR 0052).
 *
 * Pause, archive, reactivate, decline, reconsider and erase. Each one says
 * what it does before it does it, in a dialog: several change what she sees
 * when she signs in, and erase cannot be undone. Pausing, archiving and
 * declining ask for a reason, which the server refuses to go without.
 */

type Subject = {
  id: number;
  name: string;
  status: string;
  account_kind?: string;
  /** Why she cannot be erased; empty when she can (server-decided). */
  erase_blockers?: string[];
};

type Action = "pause" | "archive" | "reactivate" | "decline" | "reconsider" | "erase";

type Plan = {
  title: string;
  effects: string[];
  confirm: string;
  danger: boolean;
  needsReason: boolean;
  /** Erase only: her name has to be typed back. */
  typeName: boolean;
  send: (reason: string, typedName: string) => Promise<unknown>;
  done: string;
};

function planFor(action: Action, subject: Subject): Plan {
  const first = subject.name.split(" ")[0];
  const patch = (status: string) => (reason: string) =>
    api.patch(`/api/affiliates/${subject.id}`, { status, reason: reason || undefined });
  switch (action) {
    case "pause":
      return {
        title: `Pause ${subject.name}?`,
        effects: [
          `${first} keeps her sign-in and sees that her account is paused.`,
          "Her code keeps counting her orders, and what she earns is still paid.",
          "You can reactivate her at any time.",
        ],
        confirm: "Pause",
        danger: true,
        needsReason: true,
        typeName: false,
        send: patch("inactive"),
        done: `${subject.name} is paused.`,
      };
    case "archive":
      return {
        title: `Archive ${subject.name}?`,
        effects: [
          "Her sign-in closes.",
          "Her code stops belonging to her after this month.",
          "Her history, payroll and payments are kept.",
        ],
        confirm: "Archive",
        danger: true,
        needsReason: true,
        typeName: false,
        send: patch("archived"),
        done: `${subject.name} is archived.`,
      };
    case "reactivate":
      return {
        title: `Reactivate ${subject.name}?`,
        effects:
          subject.status === "archived"
            ? [
                `${first} can sign in again and is back on the roster.`,
                "Her code ended when she was archived: register a code for this month before her sales count again.",
              ]
            : [`${first} sees her account as normal again.`],
        confirm: "Reactivate",
        danger: false,
        needsReason: false,
        typeName: false,
        send: patch("active"),
        done: `${subject.name} is active again.`,
      };
    case "decline":
      // ADR 0058: declining deletes the application, unless something about
      // money or goods is already hers - then it is kept, as before.
      return (subject.erase_blockers?.length ?? 0) === 0
        ? {
            title: `Decline ${subject.name}'s application?`,
            effects: [
              `The application is deleted: ${first}'s sign-in, code, details and payment details. Nothing is emailed.`,
              "The code is free for another model at once.",
              "You can invite the same email again, for a new application.",
            ],
            confirm: "Decline and delete",
            danger: true,
            needsReason: true,
            typeName: false,
            send: patch("declined"),
            done: `${subject.name}'s application was declined and deleted. You can invite the same email again.`,
          }
        : {
            title: `Decline ${subject.name}'s application?`,
            effects: [
              `It can't be deleted: there is ${subject.erase_blockers!.join(", ")} on record, so it is kept as declined.`,
              `${first} sees that the application wasn't accepted this time when signing in. Nothing is emailed.`,
              "The code is released so another model can use it. You can reconsider it later.",
            ],
            confirm: "Decline",
            danger: true,
            needsReason: true,
            typeName: false,
            send: patch("declined"),
            done: `${subject.name}'s application is declined.`,
          };
    case "reconsider":
      return {
        title: `Reconsider ${subject.name}'s application?`,
        effects: [
          "It goes back under Applications, to be reviewed and approved as normal.",
          "If her code was released, check or register it again before approving.",
        ],
        confirm: "Reconsider",
        danger: false,
        needsReason: false,
        typeName: false,
        send: patch("pending"),
        done: `${subject.name}'s application is back under Applications.`,
      };
    case "erase":
      return {
        title: `Erase ${subject.name}?`,
        effects: [
          "Her account, profile, codes, terms, targets, payment details and invitations are deleted.",
          "Every audit entry about her goes too; one entry records that a model was erased, by you, and why.",
          "This cannot be undone.",
        ],
        confirm: "Erase for good",
        danger: true,
        needsReason: true,
        typeName: true,
        send: (reason, typedName) =>
          api.post(`/api/affiliates/${subject.id}/erase`, {
            reason,
            confirm_name: typedName,
          }),
        done: `${subject.name} was erased.`,
      };
  }
}

/** The dialog every action goes through. */
function Dialog({
  plan,
  name,
  onCancel,
  onDone,
}: {
  plan: Plan;
  name: string;
  onCancel: () => void;
  onDone: (message: string, result?: unknown) => void;
}) {
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    (plan.needsReason ? reasonRef.current : cancelRef.current)?.focus();
  }, [plan.needsReason]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !working) onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel, working]);

  const blocked =
    working ||
    (plan.needsReason && !reason.trim()) ||
    (plan.typeName && typed.trim() !== name.trim());

  async function go() {
    setWorking(true);
    setProblem(null);
    try {
      const result = await plan.send(reason.trim(), typed.trim());
      onDone(plan.done, result);
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : "That did not go through.");
      setWorking(false);
    }
  }

  return (
    <div className="lifecycle__layer">
      <button
        type="button"
        className="lifecycle__scrim"
        aria-label="Cancel"
        tabIndex={-1}
        onClick={() => !working && onCancel()}
      />
      <div className="lifecycle__dialog" role="dialog" aria-modal="true" aria-labelledby="lifecycle-title">
        <h2 id="lifecycle-title" className="lifecycle__title">{plan.title}</h2>
        <ul className="lifecycle__effects">
          {plan.effects.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {plan.needsReason && (
          <label className="lifecycle__field">
            <span>
              Reason <span className="lifecycle__faint">(required, kept with her record)</span>
            </span>
            <textarea
              ref={reasonRef}
              className="input lifecycle__reason"
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
        )}
        {plan.typeName && (
          <label className="lifecycle__field">
            <span>
              Type <strong>{name}</strong> to confirm
            </span>
            <input
              className="input"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              autoComplete="off"
            />
          </label>
        )}
        {problem && (
          <p className="notice notice--refused" role="alert">
            {problem}
          </p>
        )}
        <div className="lifecycle__acts">
          <button type="button" className="button" ref={cancelRef} onClick={onCancel} disabled={working}>
            Cancel
          </button>
          <button
            type="button"
            className={plan.danger ? "button lifecycle__danger" : "button button--primary"}
            onClick={go}
            disabled={blocked}
          >
            {working ? "Working…" : plan.confirm}
          </button>
        </div>
      </div>
    </div>
  );
}

const MORE_NOTE: Partial<Record<Action, string>> = {
  pause: "She keeps her sign-in; you can reactivate any time",
  archive: "Sign-in closes and her code ends this month",
  erase: "Only for a model with no orders, payroll or payments",
};

/**
 * The actions her status allows, beside the hero. Only for staff who manage
 * models; erase only for an admin, and only when the server says nothing
 * about money or parcels stands in the way.
 */
export function ModelLifecycle({
  subject,
  session,
  onChanged,
  onErased,
}: {
  subject: Subject;
  session: Session;
  onChanged: (message: string) => void;
  onErased: (message: string) => void;
}) {
  const [open, setOpen] = useState<Action | null>(null);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenu(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenu(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [menu]);

  if (!can(session, "affiliates.manage")) return null;

  const house = subject.account_kind === "house";
  const erasable = can(session, "affiliates.erase") && (subject.erase_blockers?.length ?? 1) === 0;
  const primary: Action | null =
    subject.status === "pending"
      ? "decline"
      : subject.status === "declined"
        ? "reconsider"
        : subject.status === "inactive" || subject.status === "archived"
          ? "reactivate"
          : null;
  const more: Action[] = [
    ...(subject.status === "active" && !house ? (["pause"] as Action[]) : []),
    ...(subject.status === "active" || subject.status === "inactive" ? (["archive"] as Action[]) : []),
    ...(erasable ? (["erase"] as Action[]) : []),
  ];

  return (
    <div className="lifecycle" ref={menuRef}>
      {primary && (
        <button
          type="button"
          className={primary === "decline" ? "button lifecycle__danger-outline" : "button button--primary"}
          onClick={() => setOpen(primary)}
        >
          {primary === "decline" ? "Decline" : primary === "reconsider" ? "Reconsider" : "Reactivate"}
        </button>
      )}
      {more.length > 0 && (
        <>
          <button
            type="button"
            className="button"
            aria-haspopup="menu"
            aria-expanded={menu}
            onClick={() => setMenu((value) => !value)}
          >
            More actions ▾
          </button>
          {menu && (
            <div className="lifecycle__menu" role="menu">
              {more.map((action) => (
                <button
                  key={action}
                  type="button"
                  role="menuitem"
                  className={action === "erase" ? "lifecycle__item lifecycle__item--danger" : "lifecycle__item"}
                  onClick={() => {
                    setMenu(false);
                    setOpen(action);
                  }}
                >
                  {action === "pause" ? "Pause" : action === "archive" ? "Archive" : "Erase"}
                  <small>{MORE_NOTE[action]}</small>
                </button>
              ))}
            </div>
          )}
        </>
      )}
      {open && (
        <Dialog
          plan={planFor(open, subject)}
          name={subject.name}
          onCancel={() => setOpen(null)}
          onDone={(message, result) => {
            const was = open;
            setOpen(null);
            // A declined application that was deleted has no profile left
            // to come back to (ADR 0058).
            const gone =
              was === "erase" ||
              (was === "decline" && (result as { erased?: number } | undefined)?.erased != null);
            if (gone) onErased(message);
            else onChanged(message);
          }}
        />
      )}
    </div>
  );
}

/** Approving, through the same dialog: she is emailed the moment it happens. */
export function ApproveDialog({
  subject,
  onCancel,
  onDone,
}: {
  subject: Subject;
  onCancel: () => void;
  onDone: (message: string) => void;
}) {
  const first = subject.name.split(" ")[0];
  const plan: Plan = {
    title: `Approve ${subject.name}?`,
    effects: [
      `${first} is emailed that she's approved.`,
      "Her code counts her orders, on the pay terms you set.",
      "She appears under Active.",
    ],
    confirm: "Approve and email her",
    danger: false,
    needsReason: false,
    typeName: false,
    send: () => api.patch(`/api/affiliates/${subject.id}`, { status: "active" }),
    done: "Approved. Sales on this code are being counted.",
  };
  return <Dialog plan={plan} name={subject.name} onCancel={onCancel} onDone={onDone} />;
}
