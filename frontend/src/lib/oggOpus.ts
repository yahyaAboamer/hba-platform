/**
 * A browser's voice recording, repackaged so WhatsApp shows it as a voice
 * note (ADR 0059; the plan's phase 4).
 *
 * WhatsApp draws a voice note - the waveform, the play button - only for
 * Opus sound in an Ogg file. Chrome records the same Opus sound in a WebM
 * file. So nothing is re-encoded here: each packet of sound is lifted out of
 * the WebM and written into an Ogg, byte for byte. A few hundred lines stand
 * in for a multi-megabyte encoder, and the recording loses nothing.
 *
 * The two formats: Matroska/WebM (EBML elements) in, RFC 3533 pages carrying
 * RFC 7845 Opus out.
 */

// ── Reading WebM ────────────────────────────────────────────────────────────

const SEGMENT = 0x18538067;
const CLUSTER = 0x1f43b675;
const TRACKS = 0x1654ae6b;
const TRACK_ENTRY = 0xae;
const BLOCK_GROUP = 0xa0;
const CODEC_PRIVATE = 0x63a2;
const SIMPLE_BLOCK = 0xa3;
const BLOCK = 0xa1;

/** Elements whose contents are more elements: stepped into, not over. */
const HOLDS_ELEMENTS = new Set([SEGMENT, CLUSTER, TRACKS, TRACK_ENTRY, BLOCK_GROUP]);

const NOT_WEBM = "That recording is not in a form this inbox can turn into a voice note.";

/** How many bytes a variable-length number takes, from its first byte. */
function width(first: number | undefined, most: number): number {
  if (!first) throw new Error(NOT_WEBM);
  const bytes = Math.clz32(first) - 23;
  if (bytes > most) throw new Error(NOT_WEBM);
  return bytes;
}

/** An element's id, marker bits kept, and how many bytes it took. */
function readId(bytes: Uint8Array, at: number): [number, number] {
  const length = width(bytes[at], 4);
  let id = 0;
  for (let index = 0; index < length; index += 1) id = id * 256 + (bytes[at + index] ?? 0);
  return [id, length];
}

/** A size, or null where the recorder did not know it yet (all ones). */
function readSize(bytes: Uint8Array, at: number): [number | null, number] {
  const length = width(bytes[at], 8);
  const mask = 0xff >> length;
  let value = (bytes[at] as number) & mask;
  let unknown = value === mask;
  for (let index = 1; index < length; index += 1) {
    const next = bytes[at + index] ?? 0;
    if (next !== 0xff) unknown = false;
    value = value * 256 + next;
  }
  return [unknown ? null : value, length];
}

/**
 * The Opus packets inside a WebM recording, in order, and the header the
 * recorder wrote for them (`OpusHead`), when it wrote one.
 */
export function opusPacketsFromWebm(bytes: Uint8Array): {
  head: Uint8Array | null;
  packets: Uint8Array[];
} {
  const packets: Uint8Array[] = [];
  let head: Uint8Array | null = null;
  let at = 0;
  while (at < bytes.length) {
    const [id, idLength] = readId(bytes, at);
    at += idLength;
    const [size, sizeLength] = readSize(bytes, at);
    at += sizeLength;
    if (HOLDS_ELEMENTS.has(id)) continue;
    // Only a segment or a cluster is written before its size is known.
    if (size === null) throw new Error(NOT_WEBM);
    const end = Math.min(at + size, bytes.length);
    if (id === CODEC_PRIVATE) {
      head = bytes.subarray(at, end);
    } else if (id === SIMPLE_BLOCK || id === BLOCK) {
      // Track number, two bytes of time, one of flags, then the sound.
      const [, trackLength] = readSize(bytes, at);
      const flags = bytes[at + trackLength + 2] ?? 0;
      // Several packets laced into one block: no browser records Opus so.
      if (flags & 0x06) throw new Error(NOT_WEBM);
      const sound = bytes.subarray(at + trackLength + 3, end);
      if (sound.length > 0) packets.push(sound);
    }
    at = end;
  }
  return { head, packets };
}

// ── Opus ────────────────────────────────────────────────────────────────────

const OPUS_HEAD = [0x4f, 0x70, 0x75, 0x73, 0x48, 0x65, 0x61, 0x64]; // "OpusHead"
const OPUS_TAGS = [0x4f, 0x70, 0x75, 0x73, 0x54, 0x61, 0x67, 0x73]; // "OpusTags"

/** How much sound one packet holds, in samples at 48 kHz (RFC 6716, 3.1). */
export function packetSamples(packet: Uint8Array): number {
  const toc = packet[0] ?? 0;
  const config = toc >> 3;
  let frame: number;
  if (config < 12) frame = [480, 960, 1920, 2880][config % 4] as number;
  else if (config < 16) frame = config % 2 === 0 ? 480 : 960;
  else frame = [120, 240, 480, 960][config % 4] as number;
  const code = toc & 0x03;
  const frames = code === 0 ? 1 : code === 3 ? (packet[1] ?? 0) & 0x3f : 2;
  return frame * frames;
}

/** A plain header, for a recorder that wrote none: one channel, 48 kHz. */
function defaultHead(): Uint8Array {
  const head = new Uint8Array(19);
  head.set(OPUS_HEAD);
  const view = new DataView(head.buffer);
  head[8] = 1; // version
  head[9] = 1; // channels
  view.setUint16(10, 312, true); // samples to skip at the start
  view.setUint32(12, 48000, true); // the rate it was recorded at
  view.setInt16(16, 0, true); // gain
  head[18] = 0; // channel mapping
  return head;
}

function tags(): Uint8Array {
  const vendor = [0x48, 0x42, 0x41]; // "HBA"
  const out = new Uint8Array(8 + 4 + vendor.length + 4);
  out.set(OPUS_TAGS);
  const view = new DataView(out.buffer);
  view.setUint32(8, vendor.length, true);
  out.set(vendor, 12);
  view.setUint32(12 + vendor.length, 0, true); // no comments
  return out;
}

// ── Writing Ogg ─────────────────────────────────────────────────────────────

/** Ogg's own checksum: CRC-32, polynomial 0x04c11db7, nothing reflected. */
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index << 24;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 0x80000000 ? (value << 1) ^ 0x04c11db7 : value << 1;
    }
    table[index] = value >>> 0;
  }
  return table;
})();

export function oggChecksum(bytes: Uint8Array): number {
  let crc = 0;
  for (const byte of bytes) {
    crc = ((crc << 8) ^ (CRC_TABLE[((crc >>> 24) ^ byte) & 0xff] as number)) >>> 0;
  }
  return crc;
}

const FIRST_PAGE = 0x02;
const LAST_PAGE = 0x04;

function segmentsFor(packet: Uint8Array): number {
  return Math.floor(packet.length / 255) + 1;
}

function page(
  serial: number,
  sequence: number,
  granule: number,
  flags: number,
  packets: Uint8Array[],
): Uint8Array {
  const lacing: number[] = [];
  let payload = 0;
  for (const packet of packets) {
    let left = packet.length;
    while (left >= 255) {
      lacing.push(255);
      left -= 255;
    }
    lacing.push(left);
    payload += packet.length;
  }
  const out = new Uint8Array(27 + lacing.length + payload);
  const view = new DataView(out.buffer);
  out.set([0x4f, 0x67, 0x67, 0x53]); // "OggS"
  out[4] = 0;
  out[5] = flags;
  view.setUint32(6, granule >>> 0, true);
  view.setUint32(10, Math.floor(granule / 0x100000000), true);
  view.setUint32(14, serial, true);
  view.setUint32(18, sequence, true);
  out[26] = lacing.length;
  out.set(lacing, 27);
  let at = 27 + lacing.length;
  for (const packet of packets) {
    out.set(packet, at);
    at += packet.length;
  }
  view.setUint32(22, oggChecksum(out), true);
  return out;
}

/** About a second of sound to a page, and never more than a page can index. */
const PACKETS_A_PAGE = 50;
const SEGMENTS_A_PAGE = 255;

/**
 * A WebM recording of Opus sound, as an Ogg file of the same sound.
 *
 * Throws, with words safe to show, for anything that is not such a recording
 * or holds no sound.
 */
export function webmOpusToOgg(
  webm: Uint8Array,
  serial = (Math.random() * 0xffffffff) >>> 0,
): Uint8Array {
  const { head, packets } = opusPacketsFromWebm(webm);
  if (packets.length === 0) throw new Error("The recording is empty.");
  const usable =
    head !== null && head.length >= 19 && OPUS_HEAD.every((byte, index) => head[index] === byte);

  const pages: Uint8Array[] = [
    page(serial, 0, 0, FIRST_PAGE, [usable ? head : defaultHead()]),
    page(serial, 1, 0, 0, [tags()]),
  ];
  let sequence = 2;
  let samples = 0;
  let held: Uint8Array[] = [];
  let segments = 0;
  const flush = (last: boolean) => {
    pages.push(page(serial, sequence, samples, last ? LAST_PAGE : 0, held));
    sequence += 1;
    held = [];
    segments = 0;
  };
  packets.forEach((packet, index) => {
    if (held.length >= PACKETS_A_PAGE || segments + segmentsFor(packet) > SEGMENTS_A_PAGE) {
      flush(false);
    }
    held.push(packet);
    segments += segmentsFor(packet);
    // A page says how much sound there is up to the end of its last packet.
    samples += packetSamples(packet);
    if (index === packets.length - 1) flush(true);
  });

  const out = new Uint8Array(pages.reduce((total, one) => total + one.length, 0));
  let at = 0;
  for (const one of pages) {
    out.set(one, at);
    at += one.length;
  }
  return out;
}
