/**
 * The few sentences on Production's screens that name people (ADR 0076,
 * decision 3). They come from the database with the fixed lists, so the
 * screens read exactly as before and the repository holds no names.
 */
const texts: Record<string, string> = {};
const textLists: Record<string, string[]> = {};

export function applyFixtureTexts(data: { texts?: Record<string, string>; textLists?: Record<string, string[]> }) {
  Object.assign(texts, data.texts ?? {});
  Object.assign(textLists, data.textLists ?? {});
}

export function fixtureText(key: string): string {
  return texts[key] ?? "";
}

export function fixtureList(key: string): string[] {
  return textLists[key] ?? [];
}
