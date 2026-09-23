/**
 * The interaction half of the review: does the thing actually work.
 *
 * A screenshot proves a screen renders. It proves nothing about what happens
 * when somebody presses the button, and every one of these has a way of being
 * wrong that a picture cannot show: a save that posts and does not persist, a
 * *Copy* that copies the masked value, an *Open InstaPay* that rebuilds the
 * address from the phone number instead of using the link she submitted.
 *
 * So each check **changes something and then reads it back from the server**,
 * on a fresh page load. Passing means the state survived the round trip, not
 * that a toast appeared.
 *
 * Run it **after** `review.mjs`, against the same throwaway database:
 *
 *   PLAYWRIGHT=<path>/playwright-core/index.js node actions.mjs
 *
 * **It leaves one thing changed.** Saving targets puts its cell back; editing
 * terms does not, because terms are a period somebody wrote and unwriting one
 * would be a worse lie than leaving it. So the seeded model's last editable
 * month ends on 17% commission. Re-seed before capturing screenshots again.
 */

import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const playwright = await import(
  process.env.PLAYWRIGHT
    ? pathToFileURL(process.env.PLAYWRIGHT).href
    : "playwright-core"
);
const { chromium } = playwright.chromium ? playwright : playwright.default;

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = process.env.APP_URL || "http://127.0.0.1:8123";
const OWNER = { email: "owner@example.com", password: "a-long-enough-password" };

const results = [];
const settle = (page, ms = 600) => page.waitForTimeout(ms);

function record(name, ok, evidence) {
  results.push({ name, ok, evidence });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}\n      ${evidence}`);
}

function previousMonth() {
  const now = new Date();
  const earlier = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${earlier.getFullYear()}-${String(earlier.getMonth() + 1).padStart(2, "0")}`;
}

async function signIn(browser) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1100 },
    deviceScaleFactor: 1,
    permissions: ["clipboard-read", "clipboard-write"],
  });
  const page = await context.newPage();
  await page.goto(`${APP}/sign-in`, { waitUntil: "domcontentloaded" });
  await page.fill("input[type=email]", OWNER.email);
  await page.fill("input[type=password]", OWNER.password);
  await page.click("button[type=submit]");
  await page.waitForURL((url) => !url.pathname.startsWith("/sign-in"), { timeout: 20000 });
  await settle(page, 1200);
  return { context, page };
}

// ── 1. Navigation ───────────────────────────────────────────────────────────
//
// Every sidebar destination, by clicking rather than by typing a URL: a route
// that only works when it is typed is a route nobody reaches.

async function navigation(page) {
  const expected = [
    ["Home", "/"],
    ["Models", "/affiliates"],
    ["Products", "/products"],
    ["Targets", "/targets"],
    ["Payments", "/payments"],
    ["Settings", "/settings"],
  ];
  const seen = [];
  for (const [label, path] of expected) {
    await page.goto(`${APP}/`, { waitUntil: "networkidle" });
    await page.getByRole("link", { name: new RegExp(`^${label}`) }).first().click();
    await settle(page, 700);
    const landed = new URL(page.url()).pathname;
    const heading = (await page.locator("h1").first().textContent())?.trim();
    seen.push(`${label}→${landed} (${heading})`);
    if (landed !== path) {
      record("navigation", false, `${label} went to ${landed}, expected ${path}`);
      return;
    }
  }
  record("navigation", true, seen.join("  "));
}

// ── 2. Saving targets ───────────────────────────────────────────────────────

async function savingTargets(page) {
  await page.goto(`${APP}/targets`, { waitUntil: "networkidle" });
  await settle(page, 1000);
  // The grid opens on *Record achieved*; what is saved here is what HBA asked
  // for, which is the other half of the same control.
  await page.locator("label", { hasText: "Set requirements" }).first().click();
  await settle(page, 600);

  const cell = page.locator('input[aria-label$="videos required"]').first();
  const label = await cell.getAttribute("aria-label");
  const before = await cell.inputValue();
  const after = String((Number(before) || 0) + 3);
  await cell.fill(after);
  await page.getByRole("button", { name: /^Save changes$/ }).first().click();
  await settle(page, 1800);

  // Read it back from the server, not from the page that just wrote it.
  await page.goto(`${APP}/targets`, { waitUntil: "networkidle" });
  await settle(page, 1000);
  await page.locator("label", { hasText: "Set requirements" }).first().click();
  await settle(page, 600);
  const reloaded = await page.locator(`input[aria-label="${label}"]`).first().inputValue();
  record(
    "saving targets",
    reloaded === after,
    `${label}: ${before} → ${after}, reloaded as ${reloaded}`,
  );

  // Put it back, so the screenshots and the next run start where they did.
  await page.locator(`input[aria-label="${label}"]`).first().fill(before);
  await page.getByRole("button", { name: /^Save changes$/ }).first().click();
  await settle(page, 1500);
}

// ── 3. Editing terms ────────────────────────────────────────────────────────

async function editingTerms(page) {
  await page.goto(`${APP}/affiliates?q=Sara`, { waitUntil: "networkidle" });
  await settle(page, 900);
  await page.locator("tbody tr a").first().click();
  await page.waitForLoadState("networkidle");
  const who = (await page.locator("h1").first().textContent())?.trim();
  const id = new URL(page.url()).pathname.split("/")[2];

  await page.goto(`${APP}/affiliates/${id}/compensation`, { waitUntil: "networkidle" });
  await settle(page, 1200);

  // A month with nothing agreed in it, so nothing settled is disturbed - the
  // grid refuses an approved month anyway, which is 05B doing its job.
  // The last month the grid will let anybody edit: later months are drawn
  // disabled, and an agreed month is refused outright (05B).
  const editable = page.locator("button.terms__month:not([disabled])").last();
  const monthName = (await editable.textContent())?.replace(/\s+/g, " ").trim();
  await editable.click();
  await settle(page, 400);
  await page.locator("button").filter({ hasText: "Commission only" }).first().click();
  await settle(page, 400);
  await page.locator('input[placeholder="e.g. 12"]').first().fill("17");
  await settle(page, 300);

  const save = page.locator("button").filter({ hasText: /^(Apply|Save|Set) / }).last();
  const saveText = (await save.count()) ? (await save.textContent())?.trim() : "(none)";
  if (await save.count()) await save.click();
  await settle(page, 1800);

  await page.goto(`${APP}/affiliates/${id}/compensation`, { waitUntil: "networkidle" });
  await settle(page, 1200);
  const after = (
    await page.locator("button.terms__month:not([disabled])").last().textContent()
  )
    ?.replace(/\s+/g, " ")
    .trim();
  record(
    "editing terms",
    Boolean(after && after.includes("17")),
    `${who}: ${JSON.stringify(monthName)} now reads ${JSON.stringify(after)} (saved with ${JSON.stringify(saveText)})`,
  );
}

// ── 4 and 5. Copying the destination, and opening the submitted link ────────

async function paymentDetails(page, context) {
  const previous = process.env.PREVIOUS_MONTH || previousMonth();
  await page.goto(`${APP}/payments?month=${previous}`, { waitUntil: "networkidle" });
  await settle(page, 1200);

  // A row that is *fully paid* and has a destination: its action opens the
  // detail, where the card is. A partly-paid row's action opens the record
  // form instead, which is a different screen and a different check.
  const row = page
    .locator("tbody tr")
    .filter({ hasText: "InstaPay" })
    .filter({ hasText: "Fully paid" })
    .first();
  if (!(await row.count())) {
    record("copying payment details", false, "no fully-paid row with a destination");
    return;
  }
  const shown = (await row.locator("td").nth(2).innerText()).replace(/\s+/g, " ").trim();
  await row.getByRole("button", { name: /^Copy/ }).first().click();
  await settle(page, 600);
  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  const digits = (text) => text.replace(/\D/g, "");
  record(
    "copying payment details",
    clipboard.length > 0 && digits(shown).includes(digits(clipboard)),
    `row reads ${JSON.stringify(shown)}, clipboard ${JSON.stringify(clipboard)}`,
  );

  // **By href, not by a second click on the row.** Copying re-renders the
  // row - the button swaps to *Copied* - and a locator resolved before that
  // can land on a different row afterwards. The link's target is the fact
  // being checked anyway.
  const detailPath = await row.getByRole("link", { name: /^Open$/ }).first().getAttribute("href");
  await page.goto(`${APP}${detailPath}`, { waitUntil: "networkidle" });
  await settle(page, 1500);

  const link = page.getByRole("link", { name: /Open InstaPay/ }).first();
  if (!(await link.count())) {
    record("opening the InstaPay link", false, "no Open InstaPay button on the detail card");
    return;
  }
  const href = await link.getAttribute("href");

  // **Nothing is actually fetched from ipn.eg.** The click has to be real -
  // that is the point - but the request is aborted at the edge of the browser,
  // so this review never touches a third party's server.
  let requested = null;
  await context.route("**://ipn.eg/**", (route) => {
    requested = route.request().url();
    route.abort();
  });
  const popupWaiter = page.waitForEvent("popup", { timeout: 8000 }).catch(() => null);
  await link.click();
  const popup = await popupWaiter;
  await settle(page, 900);
  const opened = requested || popup?.url();
  if (popup) await popup.close().catch(() => {});
  await context.unroute("**://ipn.eg/**");

  const submitted = await page.evaluate(() => {
    const rows = [...document.querySelectorAll(".pay-detail__dest")];
    const hit = rows.find((entry) => /link/i.test(entry.textContent || ""));
    return hit
      ? (hit.querySelector(".pay-detail__dest-value")?.textContent || "").trim()
      : null;
  });
  record(
    "opening the InstaPay link",
    Boolean(opened) && Boolean(submitted) && opened.startsWith(submitted),
    `href ${href}; opened ${opened}; card shows ${JSON.stringify(submitted)}`,
  );

  // **The link is hers, not one built from her number.** ADR 0042 turns on
  // this: a rebuilt address sends money to whoever owns that handle.
  record(
    "the link is the one she submitted",
    Boolean(href && submitted && href === submitted),
    `button href ${JSON.stringify(href)} vs card value ${JSON.stringify(submitted)}`,
  );

  // **And the same card on her profile** - the reason this check exists is
  // that the desk had it and the profile one click away printed `…291`.
  const affiliateId = detailPath.split("/")[3];
  await page.goto(`${APP}/affiliates/${affiliateId}?section=payments`, {
    waitUntil: "networkidle",
  });
  await settle(page, 1200);
  const onProfile = await page.evaluate(() => {
    const value = document.querySelector(".pay-detail__dest-value");
    return value ? value.textContent.trim() : null;
  });
  record(
    "the profile shows the same destination",
    Boolean(onProfile) && !onProfile.includes("…"),
    `profile card reads ${JSON.stringify(onProfile)}`,
  );
}

// ── 6. Viewing a receipt ────────────────────────────────────────────────────

async function viewingReceipts(page) {
  const previous = process.env.PREVIOUS_MONTH || previousMonth();
  await page.goto(`${APP}/payments?month=${previous}`, { waitUntil: "networkidle" });
  await settle(page, 1000);
  const paid = page.locator("tbody tr").filter({ hasText: "Fully paid" }).first();
  if (!(await paid.count())) {
    record("viewing receipts", false, "no settled row on the desk to open");
    return;
  }
  const openHref = await paid.getByRole("link", { name: /^Open$/ }).first().getAttribute("href");
  await page.goto(`${APP}${openHref}`, { waitUntil: "networkidle" });
  await settle(page, 1500);

  const receipt = page.locator('a[href*="/receipts/"]').first();
  if (!(await receipt.count())) {
    record("viewing receipts", false, "no receipt link on the payment detail");
    return;
  }
  await receipt.click();
  await page.waitForLoadState("networkidle");
  await settle(page, 1000);
  const body = await page.locator("body").innerText();
  const amount = body.match(/EGP [\d,]+\.\d\d/);
  record(
    "viewing receipts",
    Boolean(amount),
    `${new URL(page.url()).pathname} shows ${amount ? amount[0] : "no amount"}`,
  );
}

const browser = await chromium.launch({ headless: true });
const { context, page } = await signIn(browser);
for (const [name, run] of [
  ["navigation", () => navigation(page)],
  ["saving targets", () => savingTargets(page)],
  ["editing terms", () => editingTerms(page)],
  ["payment details", () => paymentDetails(page, context)],
  ["viewing receipts", () => viewingReceipts(page)],
]) {
  try {
    await run();
  } catch (error) {
    record(name, false, String(error).split("\n")[0].slice(0, 220));
  }
}
writeFileSync(join(HERE, "actions.json"), JSON.stringify(results, null, 1), "utf8");
await context.close();
await browser.close();
console.log(`\n${results.filter((row) => row.ok).length}/${results.length} passed`);
