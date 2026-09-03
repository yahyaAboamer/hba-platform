import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * **The accent lives in one file, and this is what keeps it there.**
 *
 * `portal-accent.css` was written with a promise attached: switching the
 * affiliate portal from HBA red to Nocturne's blurple - or to anything else -
 * is editing eight declarations and nothing else. That promise is worth
 * exactly as much as the rule underneath it, which is that no other file may
 * name an accent colour directly.
 *
 * A rule like that decays. Somebody in a hurry types `#e6001c` into a hover
 * state, nobody notices in review, and a year later the one-file change is a
 * two-day change and the promise is a lie in a comment. So it is checked
 * rather than trusted.
 *
 * The check is deliberately narrow: it asserts nothing about colour in
 * general - `portal.css` carries a whole neutral ramp and should - only that
 * **the specific values the accent file defines appear nowhere else.**
 */

const SRC = resolve(__dirname, "..", "..");
const ACCENT = resolve(SRC, "styles", "portal-accent.css");

/**
 * Comments stripped first.
 *
 * A comment that quotes the brand hex while explaining the contrast problem
 * is documentation, not a hard-coded colour - and a check that punished it
 * would be a check that discouraged the explanation. `portal-accent.css` is
 * mostly such a comment, and so is the top of this file.
 *
 * `//` is only treated as a comment when nothing precedes it on the line but
 * whitespace, so a `https://` inside a `url()` survives.
 */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** Every colour literal: `#rgb`, `#rrggbb`, `rgb()`, `rgba()`. */
function colours(source: string): string[] {
  const body = code(source);
  const hex = body.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
  const functional = body.match(/rgba?\([^)]*\)/g) ?? [];
  return [...hex, ...functional];
}

/**
 * White and black are not accent colours.
 *
 * `--accent-on` is the text that sits *on* a filled accent, so it is a
 * contrast partner rather than part of the brand - and white is legitimately
 * a surface in `tokens.css` and a raised step in `portal.css`. Including it
 * would make this check fire on files that have done nothing wrong, which is
 * how a guard gets deleted.
 */
function achromatic(colour: string): boolean {
  return /^#(fff{1,2}|f{6}|f{8}|000|0{6}|0{8})$/.test(colour);
}

/** Normalised, so `rgba(230, 0, 28, .18)` and `rgba(230,0,28,0.18)` match. */
function key(colour: string): string {
  return colour.toLowerCase().replace(/\s+/g, "");
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      return entry === "node_modules" ? [] : walk(path);
    }
    return /\.(css|tsx?)$/.test(path) ? [path] : [];
  });
}

describe("the accent is confined to portal-accent.css", () => {
  const accentCss = readFileSync(ACCENT, "utf8");

  // Only the declarations, never the comment block above them - that comment
  // quotes the brand hex and the contrast table on purpose, and a test that
  // punished it would be a test that discouraged the explanation.
  const declarations = accentCss
    .split("\n")
    .filter((line) => /^\s*--accent[a-z-]*:/.test(line))
    .join("\n");

  const accentColours = [
    ...new Set(colours(declarations).filter((c) => !achromatic(c)).map(key)),
  ];

  it("defines its accent values in declarations, not only in prose", () => {
    // If this fails the file was restructured and the extraction above is
    // reading nothing - which would make every assertion below pass vacuously.
    expect(accentColours.length).toBeGreaterThanOrEqual(3);
  });

  const others = walk(SRC).filter((path) => resolve(path) !== ACCENT);

  it.each(others.map((path) => relative(SRC, path)))(
    "%s names no accent colour directly",
    (relativePath) => {
      const found = colours(readFileSync(resolve(SRC, relativePath), "utf8"))
        .map(key)
        .filter((colour) => accentColours.includes(colour));

      expect(
        found,
        `${relativePath} hard-codes an accent colour (${[...new Set(found)].join(", ")}). ` +
          "Take it from var(--accent), var(--accent-text), var(--accent-soft) " +
          "or var(--accent-on) instead - see styles/portal-accent.css.",
      ).toEqual([]);
    },
  );
});
