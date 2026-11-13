import {
  effective,
  fill,
  fillTemplate,
  lineSent,
  messagesOf,
  previewValues,
  savedWords,
} from "../../lib/feedbackMessages";
import type { FlowStep, WordingBody, WordingItem } from "../../lib/feedbackMessages";
import { InboxIcon } from "./InboxIcon";

/**
 * What the customer's WhatsApp will show, drawn from the wording being edited
 * (the draft, not only what is saved) and the sample customer the server
 * gives. A picture of the messages, not WhatsApp itself: the real thing may
 * set a bubble a little differently, but the words, the order, what goes out
 * together and what is only conditional are exactly the server's.
 */

export type PreviewData = {
  path: string;
  body: WordingBody;
  /** What is typed now, by item key. A key not typed is what is saved. */
  drafts: Record<string, string>;
  /** Show the messages as they read when we do not know her name. */
  withName: boolean;
};

function itemOf(data: PreviewData, key: string): WordingItem | undefined {
  return data.body.items.find((item) => item.key === key);
}

/** One item's words as she would read them. */
function shown(data: PreviewData, key: string, fillIn = true): string {
  const item = itemOf(data, key);
  if (!item) return key;
  const words = effective(item, data.drafts[key] ?? savedWords(item));
  return fillIn ? fill(words, previewValues(data.body.sample, data.withName)) : words;
}

function Template({ step, data }: { step: FlowStep; data: PreviewData }) {
  const template = data.body.templates.find((candidate) => candidate.name === step.ref);
  if (!template) return null;
  return (
    <div className="fbs-wa__group">
      <div className="fbs-wa__bubble fbs-wa__bubble--locked">
        <p className="fbs-wa__lock">
          <InboxIcon name="lock" /> Approved by Meta
        </p>
        <p className="fbs-wa__text" dir="auto">
          {fillTemplate(template.body, data.body.sample)}
        </p>
      </div>
      <div className="fbs-wa__buttons">
        {template.buttons.map((title) => (
          <span key={title} className="fbs-wa__button" dir="auto">
            {title}
          </span>
        ))}
      </div>
    </div>
  );
}

/** One WhatsApp message: the lines that go out together, then its list or buttons. */
function Message({ steps, data }: { steps: FlowStep[]; data: PreviewData }) {
  const lists = steps.filter((step) => step.button);
  const buttons = steps.filter((step) => !step.button && step.options.length > 0);
  return (
    <div className="fbs-wa__group">
      <div className="fbs-wa__bubble">
        {steps.map((step, index) => {
          const { sent, note } = lineSent(data.path, step, data.body.sample);
          return (
            <div key={`${step.ref}-${index}`} className={sent ? "fbs-wa__line" : "fbs-wa__line fbs-wa__line--off"}>
              <p className="fbs-wa__text" dir="auto">
                {shown(data, step.ref)}
              </p>
              {note && <p className="fbs-wa__note">{note}</p>}
            </div>
          );
        })}
        {lists.map((step) => (
          <p key={`list-${step.ref}`} className="fbs-wa__listbtn" dir="auto">
            <InboxIcon name="list" />
            {shown(data, step.button as string)}
          </p>
        ))}
      </div>
      {lists.map((step) => (
        <div key={`sheet-${step.ref}`} className="fbs-wa__sheet">
          <p className="fbs-wa__sheet-title" dir="auto">
            {shown(data, step.button as string)}
          </p>
          <ul>
            {step.options.map((key) => (
              <li key={key} dir="auto">
                <span className="fbs-wa__radio" aria-hidden="true" />
                {shown(data, key)}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {buttons.map((step) => (
        <div key={`buttons-${step.ref}`} className="fbs-wa__buttons">
          {step.options.map((key) => (
            <span key={key} className="fbs-wa__button" dir="auto">
              {shown(data, key)}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

/** One step on its own, for the phone layout where each field carries its own preview. */
export function StepPreview({ step, data, joined = false }: { step: FlowStep; data: PreviewData; joined?: boolean }) {
  return (
    <div className="fbs-wa fbs-wa--inline">
      {joined && <p className="fbs-wa__joined">Sent in the same message as the line above.</p>}
      {step.type === "template" ? <Template step={step} data={data} /> : <Message steps={[step]} data={data} />}
    </div>
  );
}

/** The whole path, top to bottom, in a phone. */
export function PhonePreview({ data }: { data: PreviewData }) {
  const steps = data.body.flows[data.path] ?? [];
  return (
    <div className="fbs-phone" role="group" aria-label="How this path looks in WhatsApp">
      <div className="fbs-phone__bar">
        <span className="fbs-phone__avatar" aria-hidden="true">
          H
        </span>
        <span>
          <b>HBA Wear</b>
          <small>Business account</small>
        </span>
      </div>
      <div className="fbs-phone__chat fbs-wa">
        {messagesOf(steps).map((group, index) => (
          <div key={`${group[0].ref}-${index}`} className="fbs-wa__turn">
            <p className="fbs-wa__when">{group[0].when}</p>
            {group[0].type === "template" ? (
              <Template step={group[0]} data={data} />
            ) : (
              <Message steps={group} data={data} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
