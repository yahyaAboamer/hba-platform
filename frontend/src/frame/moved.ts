/**
 * Old addresses and where they went (Phase 2, Batch 2.1).
 *
 * `from` and `to` are paths; a `:id` segment stands for a run of digits, and
 * only digits - any other word in that place is not an id and is not moved.
 * Unless `exact`, whatever follows `from` is carried over to `to`.
 */
export type Moved = { from: string; to: string; exact?: boolean };

const segments = (path: string) => path.split("/").filter(Boolean);

/** Where an old address now lives, or null when the rules do not know it. */
export function movedAddress(pathname: string, rules: readonly Moved[]): string | null {
  const have = segments(pathname);
  for (const rule of rules) {
    const want = segments(rule.from);
    if (have.length < want.length || (rule.exact && have.length !== want.length)) continue;
    let id = "";
    const matches = want.every((segment, index) => {
      if (segment !== ":id") return segment === have[index];
      if (!/^\d+$/.test(have[index])) return false;
      id = have[index];
      return true;
    });
    if (!matches) continue;
    const head = segments(rule.to).map((segment) => (segment === ":id" ? id : segment));
    return `/${[...head, ...have.slice(want.length)].join("/")}`;
  }
  return null;
}
