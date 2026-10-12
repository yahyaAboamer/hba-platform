/**
 * A browser's WebM recording becomes an Ogg file of the same sound, which is
 * what WhatsApp shows as a voice note (ADR 0059). The WebM here is built by
 * hand, element by element, the way Chrome's recorder writes one.
 */
import { describe, expect, it } from "vitest";

import { oggChecksum, opusPacketsFromWebm, packetSamples, webmOpusToOgg } from "../oggOpus";

/** One EBML element: its id, its size, its contents. */
function element(id: number[], content: number[] | Uint8Array): number[] {
  const body = Array.from(content);
  const size = body.length < 127 ? [0x80 | body.length] : [0x40 | (body.length >> 8), body.length & 0xff];
  return [...id, ...size, ...body];
}

const UNKNOWN_SIZE = [0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff];

const OPUS_HEAD = [
  ...Array.from("OpusHead", (letter) => letter.charCodeAt(0)),
  1, 1, 0x38, 0x01, 0x80, 0xbb, 0x00, 0x00, 0, 0, 0,
];

/** 20 ms of fullband sound: 960 samples. The bytes after the first are filler. */
function packet(length: number, fill: number): Uint8Array {
  const bytes = new Uint8Array(length).fill(fill);
  bytes[0] = 0xf8;
  return bytes;
}

function block(sound: Uint8Array, flags = 0x80): number[] {
  return element([0xa3], [0x81, 0x00, 0x00, flags, ...sound]);
}

function webm(packets: Uint8Array[], { head = true, flags = 0x80 } = {}): Uint8Array {
  const tracks = element(
    [0x16, 0x54, 0xae, 0x6b],
    element([0xae], [
      ...element([0x86], Array.from("A_OPUS", (letter) => letter.charCodeAt(0))),
      ...(head ? element([0x63, 0xa2], OPUS_HEAD) : []),
    ]),
  );
  return new Uint8Array([
    ...element([0x1a, 0x45, 0xdf, 0xa3], [0x42, 0x82, 0x84, 0x77, 0x65, 0x62, 0x6d]),
    // The segment and the cluster are written before their sizes are known.
    0x18, 0x53, 0x80, 0x67, ...UNKNOWN_SIZE,
    ...tracks,
    0x1f, 0x43, 0xb6, 0x75, 0xff,
    ...element([0xe7], [0x00]),
    ...packets.flatMap((sound) => block(sound, flags)),
  ]);
}

type Page = { flags: number; granule: number; sequence: number; packets: Uint8Array[]; sumOk: boolean };

/** An Ogg file read back, the way a player reads it. */
function pagesOf(ogg: Uint8Array): Page[] {
  const pages: Page[] = [];
  let at = 0;
  while (at < ogg.length) {
    expect(String.fromCharCode(...ogg.subarray(at, at + 4))).toBe("OggS");
    const view = new DataView(ogg.buffer, ogg.byteOffset + at);
    const segments = ogg[at + 26] as number;
    const lacing = ogg.subarray(at + 27, at + 27 + segments);
    const size = 27 + segments + lacing.reduce((total, one) => total + one, 0);
    const whole = ogg.slice(at, at + size);
    const stated = view.getUint32(22, true);
    whole.fill(0, 22, 26);

    const packets: Uint8Array[] = [];
    let from = at + 27 + segments;
    let length = 0;
    for (const one of lacing) {
      length += one;
      if (one < 255) {
        packets.push(ogg.slice(from, from + length));
        from += length;
        length = 0;
      }
    }
    pages.push({
      flags: ogg[at + 5] as number,
      granule: view.getUint32(6, true) + view.getUint32(10, true) * 0x100000000,
      sequence: view.getUint32(18, true),
      packets,
      sumOk: oggChecksum(whole) === stated,
    });
    at += size;
  }
  return pages;
}

describe("reading the recording", () => {
  it("finds the header and every packet of sound, in order", () => {
    const sound = [packet(40, 1), packet(41, 2), packet(39, 3)];
    const found = opusPacketsFromWebm(webm(sound));

    expect(Array.from(found.head ?? [])).toEqual(OPUS_HEAD);
    expect(found.packets.map((one) => Array.from(one))).toEqual(sound.map((one) => Array.from(one)));
  });

  it("refuses what is not a recording it knows", () => {
    expect(() => opusPacketsFromWebm(new Uint8Array([0x00, 0x01, 0x02]))).toThrow(/not in a form/);
    // Several packets laced into one block.
    expect(() => opusPacketsFromWebm(webm([packet(40, 1)], { flags: 0x82 }))).toThrow(/not in a form/);
  });
});

describe("how much sound a packet holds", () => {
  it.each([
    [[0xf8], 960], // 20 ms
    [[0xfb, 0x03], 2880], // three 20 ms frames
    [[0x18], 2880], // one 60 ms frame
    [[0x68], 960], // 20 ms, the middle band
    [[0xe9], 480], // two 5 ms frames
    [[0xf1], 960], // two 10 ms frames
  ])("%j is %i samples", (bytes, samples) => {
    expect(packetSamples(new Uint8Array(bytes))).toBe(samples);
  });
});

describe("the checksum", () => {
  it("is Ogg's own", () => {
    expect(oggChecksum(new Uint8Array([]))).toBe(0);
    expect(oggChecksum(new Uint8Array([0x01]))).toBe(0x04c11db7);
  });
});

describe("the voice note", () => {
  it("is the same sound, in an Ogg file a player can read", () => {
    const sound = [packet(40, 1), packet(41, 2), packet(39, 3)];
    const pages = pagesOf(webmOpusToOgg(webm(sound), 7));

    expect(pages.every((one) => one.sumOk)).toBe(true);
    expect(pages.map((one) => one.sequence)).toEqual([0, 1, 2]);
    // The header alone on the first page, then the tags, then the sound.
    expect(pages.map((one) => one.flags)).toEqual([0x02, 0x00, 0x04]);
    expect(Array.from(pages[0]?.packets[0] ?? [])).toEqual(OPUS_HEAD);
    const tags = pages[1]?.packets[0] ?? new Uint8Array();
    expect(String.fromCharCode(...tags.subarray(0, 8))).toBe("OpusTags");
    expect(pages[2]?.packets.map((one) => Array.from(one))).toEqual(sound.map((one) => Array.from(one)));
    // Three packets of 20 ms: the last page says how much sound there is.
    expect(pages[2]?.granule).toBe(2880);
  });

  it("spreads a long recording over pages of about a second", () => {
    const sound = Array.from({ length: 120 }, (_, index) => packet(60, index));
    const pages = pagesOf(webmOpusToOgg(webm(sound), 7));

    expect(pages.every((one) => one.sumOk)).toBe(true);
    expect(pages.slice(2).map((one) => one.packets.length)).toEqual([50, 50, 20]);
    expect(pages.slice(2).map((one) => one.granule)).toEqual([48000, 96000, 115200]);
    expect(pages.map((one) => one.flags)).toEqual([0x02, 0, 0, 0, 0x04]);
    expect(pages.slice(2).flatMap((one) => one.packets).map((one) => one[1])).toEqual(
      sound.map((one) => one[1]),
    );
  });

  it("keeps a packet whose length is an exact multiple of 255", () => {
    const sound = [packet(255, 9), packet(510, 8), packet(3, 7)];
    const pages = pagesOf(webmOpusToOgg(webm(sound), 7));

    expect(pages[2]?.packets.map((one) => one.length)).toEqual([255, 510, 3]);
  });

  it("writes a plain header when the recorder wrote none", () => {
    const pages = pagesOf(webmOpusToOgg(webm([packet(40, 1)], { head: false }), 7));

    const head = pages[0]?.packets[0] ?? new Uint8Array();
    expect(String.fromCharCode(...head.subarray(0, 8))).toBe("OpusHead");
    expect(head[9]).toBe(1); // one channel
  });

  it("says so when there is no sound in it", () => {
    expect(() => webmOpusToOgg(webm([]))).toThrow("The recording is empty.");
  });
});
