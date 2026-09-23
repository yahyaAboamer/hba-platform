/**
 * Diff the digests `review.mjs` wrote, and say what differs in words.
 *
 * Two screenshots side by side find a broken layout and nothing else. The
 * differences that matter in this review are mostly *writing*: a tab called
 * *Applications* against one called *Pending*, a heading that lost its unit, a
 * button the export has and the app does not. Those are invisible to the eye
 * at 1280 and obvious in a set difference.
 *
 * Reports, per step and width:
 *   - headings, tab and button labels present on one side only
 *   - any `E£` still rendered, which the approved design never writes
 *   - heading and body typeface, weight and colour where they disagree
 *   - the frame's own scroll state, because "scrolling" is on the list
 *
 * A difference is not automatically a fault: the app carries real data and
 * the export carries a fixture, so names, months and figures differ by
 * construction and are filtered out here rather than read one by one.
 */

import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = join(HERE, "shots");

/** Text that differs because the data differs, not because the design does. */
const DATA_SHAPED = [
  /EGP|E£/,
  /\d{1,3}(,\d{3})*(\.\d\d)?/,
  /January|February|March|April|May|June|July|August|September|October|November|December/,
  /^\d+$/,
  /^[·—–-]$/,
];

const NAMES = [
  "Sara Edrees", "Malak Fahmy", "Hana Wagih", "Yahya Aboamer", "Omar Sabry",
  "Nadine Kamal", "Farida Zaki", "Youssef Adel", "Laila Mostafa", "Aya Sherif",
  "Dina Rashad", "Jana Selim", "Mariam Adel", "Rana Fouad", "Salma Hegazy",
  "Tarek Aziz", "Yara Kassem", "Ziad Nabil", "Zeina Hamdy", "Nour Eldin",
  "Habiba Sami", "Karim Diab", "Nour Hassan",
];

/**
 * The signed-in account, which is a fixture on one side and a seed on the
 * other, and the shop chrome that carries it. Neither says anything about the
 * design, and both appear on every screen.
 */
const CHROME = [
  "Yahya", "admin", "Marketing", "HBAAdminhbawear.store", "YYahyaadmin▾",
  "N", "Y", "S", "M", "▾", "▼", "←", "→", "⋯", "✕", "×", "9:41",
];

const isData = (s) =>
  DATA_SHAPED.some((re) => re.test(s)) ||
  NAMES.some((n) => s.includes(n)) ||
  CHROME.includes(s);

/**
 * **A line that is several of the other side's lines, joined.**
 *
 * A table header is one `<tr>` in the app and five grid cells in the export.
 * `innerText` renders the first as `MODEL TO RECEIVE DESTINATION STATE NEXT
 * ACTION` and the second as five lines, and set arithmetic calls that six
 * differences. It is none: it is the same words in the same order, marked up
 * two ways. Anything that reassembles from a consecutive run on the other
 * side is dropped.
 */
function assembles(line, other) {
  const want = line.replace(/\s+/g, " ").trim().toUpperCase();
  if (want.length < 6) return false;
  for (let i = 0; i < other.length; i++) {
    let joined = "";
    for (let j = i; j < Math.min(i + 12, other.length); j++) {
      joined = joined ? `${joined} ${other[j]}` : other[j];
      const got = joined.replace(/\s+/g, " ").trim().toUpperCase();
      if (got === want) return true;
      if (got.length > want.length) break;
    }
  }
  return false;
}

/**
 * **A line that is part of one of the other side's lines.**
 *
 * The other half of the same markup problem: a tab strip is six `button`s in
 * the app and one flex row in the export, so `innerText` gives six lines
 * against one. `assembles` catches the joined side; this catches the split
 * one. Applied to prose only, never to the control list - a *Copy* button
 * that exists on one side and not the other is exactly the finding this
 * review is for, and it would vanish into any row that happens to say "copy".
 */
function containedIn(line, other) {
  const needle = line.replace(/\s+/g, " ").trim().toUpperCase();
  if (needle.length < 4) return false;
  return other.some((candidate) => {
    const hay = candidate.replace(/\s+/g, " ").trim().toUpperCase();
    return hay.length > needle.length && hay.includes(needle);
  });
}

/** Strip trailing counts: the export's *Active 19* is our *Active 20*. */
const shape = (s) => s.replace(/\s*\d[\d,]*\s*$/, "").trim();

function only(a, b, { prose = false } = {}) {
  const them = new Set(b.map(shape));
  const seen = new Set();
  return a
    .map(shape)
    .filter((s) => s && !them.has(s) && !isData(s))
    .filter((s) => !assembles(s, b))
    .filter((s) => !(prose && containedIn(s, b)))
    .filter((s) => (seen.has(s) ? false : seen.add(s)));
}

function load(side, id, width) {
  const path = join(SHOTS, side, `${id}-${width}.json`);
  return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : null;
}

const steps = new Map();
for (const side of ["export", "app"]) {
  const dir = join(SHOTS, side);
  if (!existsSync(dir)) continue;
  for (const file of readdirSync(dir)) {
    const hit = /^(.+)-(\d+)\.json$/.exec(file);
    if (hit) steps.set(`${hit[1]}|${hit[2]}`, [hit[1], Number(hit[2])]);
  }
}

let faults = 0;
for (const [, [id, width]] of [...steps].sort()) {
  const ref = load("export", id, width);
  const app = load("app", id, width);
  if (!ref || !app) {
    console.log(`\n## ${id} @ ${width}\n  MISSING ${!ref ? "export" : "app"} capture`);
    faults++;
    continue;
  }
  const lines = [];

  // Wording first: every visible line on one side and not the other. This is
  // the check that finds a renamed tab or a heading that lost its unit.
  const wMissing = only(ref.runs || [], app.runs || [], { prose: true });
  const wExtra = only(app.runs || [], ref.runs || [], { prose: true });
  if (wMissing.length) lines.push(`  wording only in export: ${JSON.stringify(wMissing.slice(0, 20))}`);
  if (wExtra.length) lines.push(`  wording only in app:    ${JSON.stringify(wExtra.slice(0, 20))}`);

  const bMissing = only(ref.buttons, app.buttons);
  const bExtra = only(app.buttons, ref.buttons);
  if (bMissing.length) lines.push(`  control only in export: ${JSON.stringify(bMissing.slice(0, 14))}`);
  if (bExtra.length) lines.push(`  control only in app:    ${JSON.stringify(bExtra.slice(0, 14))}`);

  const oldMoney = app.money.filter((m) => m.includes("E£"));
  if (oldMoney.length) lines.push(`  CURRENCY still E£:      ${JSON.stringify(oldMoney.slice(0, 4))}`);
  const badShape = app.money.filter((m) => /^EGP\d/.test(m));
  if (badShape.length) lines.push(`  CURRENCY missing space: ${JSON.stringify(badShape.slice(0, 4))}`);

  for (const part of ["heading", "body"]) {
    const a = ref[part];
    const b = app[part];
    if (!a || !b) continue;
    if (a.family !== b.family) lines.push(`  ${part} face: export ${a.family} / app ${b.family}`);
    if (part === "body" && a.colour !== b.colour)
      lines.push(`  body ink: export ${a.colour} / app ${b.colour}`);
  }
  if (ref.background !== app.background)
    lines.push(`  background: export ${ref.background} / app ${app.background}`);

  const refScrolls = ref.scrollHeight > ref.clientHeight + 2;
  const appScrolls = app.scrollHeight > app.clientHeight + 2;
  if (refScrolls !== appScrolls)
    lines.push(`  scrolling: export ${refScrolls ? "scrolls" : "fits"} / app ${appScrolls ? "scrolls" : "fits"}`);

  if (lines.length) {
    faults += lines.length;
    console.log(`\n## ${id} @ ${width}`);
    console.log(lines.join("\n"));
  } else {
    console.log(`\n## ${id} @ ${width}\n  matched`);
  }
}
console.log(`\n${faults} difference line(s)`);
