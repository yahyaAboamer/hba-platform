import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * **No staff screen still points at an address from before the frame.**
 *
 * Batch 2.1 moved every staff address under its department (ADR 0068), and an
 * old address still works only because it is redirected - once, with the page
 * flashing past. A link written the old way would keep working, and nobody
 * would notice until the redirects are retired. So it is read for rather than
 * trusted.
 *
 * The staff code is `departments/`, `screens/`, `components/`, `frame/`,
 * `lib/` and `App.tsx`. The
 * model portal is not scanned: her addresses (`/payments`, `/targets`) are her
 * own and are the ones in her emails. The one file that names the old
 * addresses on purpose is the list of where they went.
 */

const SRC = resolve(__dirname, "..");
const SCANNED = ["departments", "screens", "components", "frame", "lib"];
/** Files straight in `src/` that are staff code too. */
const SCANNED_FILES = ["App.tsx"];
const NAMES_OLD_ADDRESSES = ["departments/affiliates/department.tsx"];

function files(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return name === "__tests__" ? [] : files(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

/** Comments out: a comment that quotes an old address is documentation. */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "$1");
}

/** An address at the start of a string or template literal. */
const OLD_ADDRESSES: [string, RegExp][] = [
  ["/products", /["'`]\/products(?![\w-])/],
  ["/targets", /["'`]\/targets(?![\w-])/],
  ["/payments", /["'`]\/payments(?![\w-])/],
  ["/payroll", /["'`]\/payroll(?![\w-])/],
  ["/orders", /["'`]\/orders(?![\w-])/],
  ["/affiliates (bare)", /["'`]\/affiliates(?=["'`?#])/],
  ["/affiliates/invite", /\/affiliates\/invite(?![\w-])/],
  ["/affiliates/${id}", /["'`]\/affiliates\/\$\{/],
  ['"/affiliates/" + id', /["'`]\/affiliates\/["'`]\s*\+/],
  ["/?month (the old Home)", /["'`]\/\?/],
];

describe("the staff screens' links", () => {
  const found = [
    ...SCANNED.flatMap((directory) => files(join(SRC, directory))),
    ...SCANNED_FILES.map((name) => join(SRC, name)),
  ]
    .map((path) => relative(SRC, path).split(sep).join("/"))
    .filter((path) => !NAMES_OLD_ADDRESSES.includes(path));

  it("reads the screens it means to", () => {
    expect(found.length).toBeGreaterThan(40);
    expect(found).toContain("departments/affiliates/Payments.tsx");
  });

  it("points none of them at an address from before the frame", () => {
    const stale: string[] = [];
    for (const path of found) {
      const body = code(readFileSync(join(SRC, path), "utf8"));
      for (const [name, pattern] of OLD_ADDRESSES) {
        if (pattern.test(body)) stale.push(`${path} still points at ${name}`);
      }
    }
    expect(stale).toEqual([]);
  });
});
