/**
 * Recording a voice note in the browser (ADR 0059; the plan's phase 4).
 *
 * WhatsApp shows a voice note only for Opus sound in an Ogg file. Firefox
 * records exactly that. Chrome records the same sound in a WebM file, which
 * is repackaged here without re-encoding (`oggOpus.ts`). Safari records
 * another kind of sound altogether; that is sent as an audio file, which
 * plays for her but is not drawn as a voice note.
 */

import { webmOpusToOgg } from "./oggOpus";

/** Tried in this order: the first the browser can record is used. */
const FORMS = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"];

export const NO_MICROPHONE =
  "The microphone is blocked for this site. Allow it in the browser to record a voice note.";

export type VoiceNote = {
  file: Blob;
  filename: string;
  /** Whether WhatsApp will draw it as a voice note, not as an audio file. */
  voice: boolean;
};

export type Recording = {
  /** Stop, and hand back what was recorded, ready to send. */
  stop: () => Promise<VoiceNote>;
  /** Stop and keep nothing. */
  cancel: () => void;
};

export function canRecord(): boolean {
  return (
    typeof MediaRecorder === "function" &&
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function"
  );
}

/** What was recorded, in the form WhatsApp takes it. */
export async function asVoiceNote(recorded: Blob): Promise<VoiceNote> {
  const kind = recorded.type.split(";")[0]?.trim().toLowerCase();
  if (kind === "audio/ogg") {
    return { file: new Blob([recorded], { type: "audio/ogg" }), filename: "voice-note.ogg", voice: true };
  }
  if (kind === "audio/webm") {
    const ogg = webmOpusToOgg(new Uint8Array(await recorded.arrayBuffer()));
    return { file: new Blob([ogg], { type: "audio/ogg" }), filename: "voice-note.ogg", voice: true };
  }
  if (kind === "audio/mp4") {
    return { file: new Blob([recorded], { type: "audio/mp4" }), filename: "voice-note.m4a", voice: false };
  }
  throw new Error("This browser records sound in a form WhatsApp does not take.");
}

/**
 * The same sound in one channel.
 *
 * Asking the microphone for one channel is only a request, and a headset or
 * an audio interface may still hand over two. WhatsApp takes a voice note in
 * mono only, so anything that is not already one channel is mixed down
 * before it is recorded.
 */
function asOneChannel(stream: MediaStream): { stream: MediaStream; close: () => void } {
  const untouched = { stream, close: () => undefined };
  const channels = stream.getAudioTracks?.()[0]?.getSettings?.().channelCount;
  if (channels === 1 || typeof AudioContext !== "function") return untouched;
  try {
    const context = new AudioContext();
    const mixed = new MediaStreamAudioDestinationNode(context, {
      channelCount: 1,
      channelCountMode: "explicit",
    });
    context.createMediaStreamSource(stream).connect(mixed);
    return { stream: mixed.stream, close: () => void context.close() };
  } catch {
    return untouched;
  }
}

/**
 * Start recording from the microphone. The browser asks for it the first
 * time; a refusal is reported in words safe to show.
 */
export async function startRecording(): Promise<Recording> {
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      // One channel: WhatsApp takes a voice note in mono only.
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch {
    throw new Error(NO_MICROPHONE);
  }
  const single = asOneChannel(stream);
  const release = () => {
    stream.getTracks().forEach((track) => track.stop());
    single.close();
  };

  const form = FORMS.find((candidate) => MediaRecorder.isTypeSupported(candidate));
  let recorder: MediaRecorder;
  try {
    recorder = new MediaRecorder(
      single.stream,
      form ? { mimeType: form, audioBitsPerSecond: 32_000 } : undefined,
    );
  } catch {
    release();
    throw new Error("This browser cannot record a voice note.");
  }
  const parts: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) parts.push(event.data);
  };
  recorder.start();

  return {
    cancel() {
      recorder.onstop = null;
      if (recorder.state !== "inactive") recorder.stop();
      release();
    },
    stop: () =>
      new Promise<VoiceNote>((resolve, reject) => {
        recorder.onstop = () => {
          release();
          asVoiceNote(new Blob(parts, { type: recorder.mimeType || form || "" })).then(resolve, reject);
        };
        if (recorder.state === "inactive") {
          reject(new Error("The recording had already stopped."));
        } else {
          recorder.stop();
        }
      }),
  };
}
