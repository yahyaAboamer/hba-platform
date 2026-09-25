/**
 * Batch J: the checks for the work of 25 September - *Refresh now* first,
 * then the admin operations, interface and Settings groups.
 *
 *     PLAYWRIGHT=<playwright>/index.js node batch-j.mjs <step> [<step> ...]
 *
 * Same set-up as `review.mjs` (README.md), except that the application is
 * started through `simulated_shopify.py`, so the Shopify refresh runs the real
 * route, worker and sweep against a simulated shop whose answer is the word in
 * `SIMULATED_SHOPIFY_MODE`. Writes to `shots/batch-j/` and appends what it saw
 * to `shots/batch-j/checks.txt`; never touches `shots/app` or `shots/export`.
 */
import { execFileSync } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const playwright = await import(
  process.env.PLAYWRIGHT ? pathToFileURL(process.env.PLAYWRIGHT).href : "playwright-core"
);
const { chromium } = playwright.chromium ? playwright : playwright.default;

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "shots", "batch-j");
mkdirSync(OUT, { recursive: true });
const CHECKS = join(OUT, "checks.txt");

const APP = process.env.APP_URL || "http://127.0.0.1:8123";
const EXPORTS = process.env.EXPORT_URL || "http://127.0.0.1:8899";
const ADMIN_EXPORT = `${EXPORTS}/Admin%20Dashboard.dc.html`;
const PORTAL_EXPORT = `${EXPORTS}/Affiliate%20Portal%20v3.dc.html`;
const MODE = process.env.SIMULATED_SHOPIFY_MODE;
const OWNER = { email: "owner@example.com", password: "a-long-enough-password" };
const MODEL = { email: "sara@example.com", password: "a-long-enough-password" };

const settle = (page, ms = 550) => page.waitForTimeout(ms);
const log = (line) => {
  console.log(line);
  appendFileSync(CHECKS, `${line}\n`);
};
const shop = (mode) => writeFileSync(MODE, mode);

async function signIn(browser, who, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(`${APP}/sign-in`, { waitUntil: "domcontentloaded" });
  await page.fill("input[type=email]", who.email);
  await page.fill("input[type=password]", who.password);
  await page.click("button[type=submit]");
  await page.waitForURL((url) => !url.pathname.startsWith("/sign-in"), { timeout: 15000 });
  await settle(page, 800);
  return { context, page };
}

/**
 * Where the export's two outside requests come from, when the machine cannot
 * reach them directly.
 *
 * The export loads React 18.3.1 from unpkg and Inter from Google Fonts. In the
 * cloud session unpkg is refused by the network policy, so React's UMD files
 * come from the same version installed from the npm registry
 * (`EXPORT_VENDOR`, a folder holding `node_modules/react` and `react-dom` at
 * 18.3.1); fonts are fetched with curl, which trusts the proxy's CA. Unset,
 * nothing is intercepted and the page loads as it did on the Windows machine.
 */
async function exportRoutes(context) {
  const vendor = process.env.EXPORT_VENDOR;
  if (!vendor) return;
  await context.route(/unpkg\.com\/(react|react-dom)@18\.3\.1\/umd\/(.+)$/, (route) => {
    const [, pkg, file] = route.request().url().match(/unpkg\.com\/(react|react-dom)@18\.3\.1\/umd\/(.+)$/);
    route.fulfill({ contentType: "application/javascript", body: readFileSync(join(vendor, "node_modules", pkg, "umd", file)) });
  });
  await context.route(/fonts\.(googleapis|gstatic)\.com/, (route) => {
    const url = route.request().url();
    const body = execFileSync("curl", ["-sS", "-A", "Mozilla/5.0 Chrome/140", url]);
    route.fulfill({ contentType: url.includes("googleapis") ? "text/css" : "font/woff2", body });
  });
}

/** The export at a width, its frame asserted to be exactly that wide. */
async function openExport(browser, url, width, frame = ".ad") {
  const context = await browser.newContext({
    viewport: { width: width + 220, height: 1160 },
    deviceScaleFactor: 1,
  });
  await exportRoutes(context);
  const ref = await context.newPage();
  await ref.goto(url, { waitUntil: "networkidle" });
  await settle(ref, 1200);
  if (width === 1440) {
    await ref.locator("label.seg-opt", { hasText: "1440" }).first().click();
    await settle(ref, 700);
  }
  const actual = await ref.evaluate((sel) => document.querySelector(sel).getBoundingClientRect().width, frame);
  if (actual !== width) throw new Error(`export frame is ${actual}px, expected ${width}px`);
  return { context, ref };
}

const exportNav = (ref, index) => ref.locator(".ad > div:first-child button").nth(index);
const NAV = { home: 0, models: 1, products: 2, targets: 3, payments: 4, settings: 5 };

async function exportTab(ref, label) {
  await ref.locator(".ad > div:nth-child(2) button").filter({ hasText: new RegExp(`^\\s*${label}`) }).first().click();
  await settle(ref);
}

/** Computed style of the first element matching, for measured comparisons. */
async function style(page, locator) {
  return locator.first().evaluate((el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {
      text: el.innerText.trim().slice(0, 80),
      font: `${s.fontSize} ${s.fontWeight} ${s.fontFamily.split(",")[0]}`,
      color: s.color, background: s.backgroundColor, border: s.border,
      radius: s.borderRadius, padding: s.padding, height: Math.round(r.height),
    };
  });
}

// ── Steps ───────────────────────────────────────────────────────────────────

const steps = {};

/** *Refresh now*: the whole action, success, failure, retry, reload. */
steps.refresh = async (browser) => {
  for (const width of [1280, 1440]) {
    const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
    let posts = 0;
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith("/api/operations/refresh")) posts += 1;
    });
    const button = page.locator("button.sync__refresh");
    const state = page.locator(".sync__state");
    const api = () => page.evaluate(async () => (await (await fetch("/api/operations/sync")).json()).refresh);

    shop("ok");
    await page.goto(`${APP}/settings?section=shopify`, { waitUntil: "networkidle" });
    await settle(page, 700);
    log(`[${width}] arrive: "${(await state.innerText()).trim()}" / button "${(await button.innerText()).trim()}"`);
    await page.screenshot({ path: join(OUT, `app-shopify-arrive-${width}.png`) });

    // A slow shop, so *Refreshing* can be seen; two clicks.
    shop("slow");
    const before = (await api()).last_success_at;
    await button.click();
    await button.click({ force: true, timeout: 1000 }).catch(() => undefined);
    await page.waitForFunction(() => document.querySelector("button.sync__refresh")?.textContent === "Refreshing…");
    const during = await api();
    log(`[${width}] after click: "${(await state.innerText()).trim()}" / button "${(await button.innerText()).trim()}" disabled=${await button.isDisabled()} / server state=${during.state} last_success_at unchanged=${during.last_success_at === before}`);
    await page.screenshot({ path: join(OUT, `app-shopify-refreshing-${width}.png`) });
    await page.waitForFunction(() => document.querySelector("button.sync__refresh")?.textContent === "Refresh now", null, { timeout: 30000 });
    const done = await api();
    log(`[${width}] finished: "${(await state.innerText()).trim()}" / server state=${done.state} last_success_at moved=${done.last_success_at !== before} / refresh POSTs=${posts}`);
    const jobs = await page.evaluate(async () => (await (await fetch("/api/operations/sync")).json()).jobs);
    log(`[${width}] jobs after: ${JSON.stringify(jobs)}`);
    await page.screenshot({ path: join(OUT, `app-shopify-succeeded-${width}.png`) });

    await page.reload({ waitUntil: "networkidle" });
    await settle(page, 700);
    log(`[${width}] reload: "${(await state.innerText()).trim()}"`);

    // Shopify answers 429: the failure, with the last success kept.
    shop("429");
    const kept = (await api()).last_success_at;
    await button.click();
    await page.waitForFunction(() => document.querySelector(".sync__state")?.textContent.includes("Last refresh failed"), null, { timeout: 30000 });
    const failed = await api();
    log(`[${width}] 429: "${(await state.innerText()).trim()}" / button "${(await button.innerText()).trim()}" / last_success_at kept=${failed.last_success_at === kept}`);
    log(`[${width}] 429 line: "${(await page.locator(".sync__error").first().innerText()).trim()}"`);
    await page.screenshot({ path: join(OUT, `app-shopify-failed-${width}.png`) });
    await page.reload({ waitUntil: "networkidle" });
    await settle(page, 700);
    log(`[${width}] reload after failure: "${(await state.innerText()).trim()}" / button "${(await button.innerText()).trim()}"`);

    // *Try again*, and the shop answers.
    shop("ok");
    await button.click();
    await page.waitForFunction(() => document.querySelector("button.sync__refresh")?.textContent === "Refresh now", null, { timeout: 30000 });
    const again = await api();
    log(`[${width}] try again: "${(await state.innerText()).trim()}" / server state=${again.state} moved=${again.last_success_at !== kept}`);

    log(`[${width}] app button: ${JSON.stringify(await style(page, button))}`);
    log(`[${width}] app state: ${JSON.stringify(await style(page, page.locator(".sync__state span").nth(1)))}`);
    log(`[${width}] app when: ${JSON.stringify(await style(page, page.locator(".sync__when")))}`);
    await context.close();

    const { context: rc, ref } = await openExport(browser, ADMIN_EXPORT, width);
    await exportNav(ref, NAV.settings).click();
    await settle(ref);
    await exportTab(ref, "Shopify and sync");
    await ref.locator(".ad").screenshot({ path: join(OUT, `export-shopify-${width}.png`) });
    const refButton = ref.locator(".ad button", { hasText: "Refresh now" });
    log(`[${width}] export button: ${JSON.stringify(await style(ref, refButton))}`);
    const refState = ref.locator(".ad span", { hasText: /^Connected$/ });
    log(`[${width}] export state: ${JSON.stringify(await style(ref, refState))}`);
    log(`[${width}] export when: ${JSON.stringify(await style(ref, ref.locator(".ad span", { hasText: "last successful refresh" })))}`);
    await rc.close();
  }
};

/** Admin Targets: words, column widths, a save, reload, and two refusals. */
steps.targets = async (browser) => {
  const columns = (page, head, row) => page.evaluate(([h, r]) => {
    const heads = [...document.querySelectorAll(h)].map((el) => {
      const cs = getComputedStyle(el);
      return `${el.textContent.trim()}:${Math.round(el.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight))}`;
    });
    const rows = [...document.querySelectorAll(r)].slice(0, 3).map((el) => Math.round(el.getBoundingClientRect().height));
    return { heads, rows };
  }, [head, row]);
  for (const width of [1280, 1440]) {
    const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
    await page.goto(`${APP}/targets`, { waitUntil: "networkidle" });
    await settle(page, 800);
    await page.screenshot({ path: join(OUT, `app-targets-${width}.png`) });
    log(`[${width}] app columns (content px) and first rows: ${JSON.stringify(await columns(page, "thead th", "tbody tr"))}`);
    const words = await page.locator("td.targets__outcome").evaluateAll((cells) => cells.map((c) => c.innerText.replace(/\n/g, " | ")));
    log(`[${width}] app Recorded cells (September): ${JSON.stringify(words)}`);
    const updated = await page.locator("td.targets__updated").first().evaluate((el) => ({ text: el.innerText, lines: Math.round(el.getBoundingClientRect().height / 19) }));
    log(`[${width}] Last updated first cell: ${JSON.stringify(updated)}`);
    for (const [cls, label] of [["targets__met", "Target met"], ["targets__missed", "other"], ["targets__unknown", "No record yet"]]) {
      if (await page.locator(`.${cls}`).count()) log(`[${width}] tone ${label}: ${JSON.stringify(await style(page, page.locator(`.${cls}`)))}`);
    }

    if (width === 1280) {
      const input = page.getByLabel("Jana Selim videos achieved");
      const cell = page.locator("tr", { has: input }).locator("td.targets__outcome");
      log(`[${width}] Jana before: ${JSON.stringify(await cell.innerText())} value=${await input.inputValue()}`);

      // Refused: not a whole number. Nothing saved, the typing kept.
      await input.fill("x");
      await page.getByRole("button", { name: "Save changes" }).click();
      await settle(page);
      log(`[${width}] non-number: alert=${JSON.stringify(await page.getByRole("alert").first().innerText().catch(() => ""))} value kept=${(await input.inputValue()) === "x"}`);

      // Refused: somebody else saved the month first.
      await input.fill("2");
      const other = await context.newPage();
      await other.goto(`${APP}/targets`, { waitUntil: "networkidle" });
      await settle(other, 600);
      await other.getByLabel("Farida Zaki stories achieved").fill("7");
      await other.getByRole("button", { name: "Save changes" }).click();
      await settle(other, 900);
      await page.getByRole("button", { name: "Save changes" }).click();
      await settle(page, 900);
      log(`[${width}] stale revision: alert=${JSON.stringify(await page.getByRole("alert").first().innerText().catch(() => ""))} value kept=${(await input.inputValue()) === "2"}`);
      await page.screenshot({ path: join(OUT, `app-targets-stale-${width}.png`) });
      await page.reload({ waitUntil: "networkidle" });
      await settle(page, 700);
      log(`[${width}] after reload: Jana=${JSON.stringify(await cell.innerText())} value=${await input.inputValue()}`);

      // Saved: 2 of 4 in the running month is In progress, and survives a reload.
      await input.fill("2");
      await page.getByRole("button", { name: "Save changes" }).click();
      await settle(page, 1000);
      log(`[${width}] saved 2: ${JSON.stringify(await cell.innerText())}`);
      await page.reload({ waitUntil: "networkidle" });
      await settle(page, 700);
      log(`[${width}] reload: ${JSON.stringify(await cell.innerText())} value=${await input.inputValue()}`);
      await page.screenshot({ path: join(OUT, `app-targets-in-progress-${width}.png`) });
      // Put back, both.
      await input.fill("4");
      await page.getByLabel("Farida Zaki stories achieved").fill("8");
      await page.getByRole("button", { name: "Save changes" }).click();
      await settle(page, 1000);
      await page.reload({ waitUntil: "networkidle" });
      await settle(page, 700);
      log(`[${width}] put back: ${JSON.stringify(await cell.innerText())} value=${await input.inputValue()}`);
      await other.close();
    }

    await page.goto(`${APP}/targets?month=${previousMonth()}`, { waitUntil: "networkidle" });
    await settle(page, 800);
    const past = await page.locator("td.targets__outcome").evaluateAll((cells) => cells.map((c) => c.innerText.replace(/\n/g, " | ")));
    log(`[${width}] app Recorded cells (${previousMonth()}): ${JSON.stringify(past)}`);
    await page.screenshot({ path: join(OUT, `app-targets-past-${width}.png`) });
    await context.close();

    const { context: rc, ref } = await openExport(browser, ADMIN_EXPORT, width);
    await exportNav(ref, NAV.targets).click();
    await settle(ref, 800);
    await ref.locator(".ad").screenshot({ path: join(OUT, `export-targets-${width}.png`) });
    const refCols = await ref.evaluate(() => {
      const head = [...document.querySelectorAll(".ad span")].find((el) => el.textContent.trim() === "Model").parentElement;
      return [...head.children].map((el) => `${el.textContent.trim()}:${Math.round(el.getBoundingClientRect().width)}`);
    });
    log(`[${width}] export columns: ${JSON.stringify(refCols)}`);
    for (const word of ["Target met", "In progress", "No record yet", "Recorded zero"]) {
      const loc = ref.locator(".ad span", { hasText: new RegExp(`^${word}$`) });
      if (await loc.count()) log(`[${width}] export tone ${word}: ${JSON.stringify(await style(ref, loc))}`);
    }
    await rc.close();
  }
};

/** Recording a payment: the export's own `vRecord` view against ours, and a save. */
steps.record = async (browser) => {
  const texts = (page, scope) => page.locator(scope).evaluate((el) => el.innerText.split("\n").map((t) => t.trim()).filter(Boolean));
  for (const width of [1280, 1440]) {
    const { context: rc, ref } = await openExport(browser, ADMIN_EXPORT, width);
    await exportNav(ref, NAV.payments).click();
    await settle(ref, 800);
    await ref.locator(".ad button", { hasText: /^Record payment$/ }).first().click();
    await settle(ref, 800);
    await ref.locator(".ad button", { hasText: /^Record payment$/ }).first().click();
    await settle(ref, 800);
    await ref.locator(".ad").screenshot({ path: join(OUT, `export-record-${width}.png`) });
    const refMain = ".ad > div:nth-child(2)";
    log(`[${width}] export vRecord: ${JSON.stringify(await texts(ref, refMain))}`);
    log(`[${width}] export amount input: ${JSON.stringify(await style(ref, ref.locator("#ad-recamt")))}`);
    log(`[${width}] export save: ${JSON.stringify(await style(ref, ref.locator(".ad button", { hasText: /^Record payment$/ })))}`);
    await rc.close();

    const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
    await page.goto(`${APP}/payments?month=${previousMonth()}`, { waitUntil: "networkidle" });
    await settle(page, 800);
    await page.locator("main").getByRole("link", { name: /Nadine Kamal/ }).first().click();
    await page.waitForLoadState("networkidle");
    await settle(page, 700);
    await page.locator("main").getByRole("link", { name: /^Record payment$/ }).or(page.locator("main").getByRole("button", { name: /^Record payment$/ })).first().click();
    await page.waitForLoadState("networkidle");
    await settle(page, 700);
    await page.screenshot({ path: join(OUT, `app-record-${width}.png`) });
    log(`[${width}] app record: ${JSON.stringify(await texts(page, "main"))}`);
    log(`[${width}] app amount input: ${JSON.stringify(await style(page, page.getByLabel("Amount transferred, EGP")))}`);
    log(`[${width}] app save: ${JSON.stringify(await style(page, page.getByRole("button", { name: "Record payment" })))}`);

    if (width === 1280) {
      const amount = page.getByLabel("Amount transferred, EGP");
      await amount.fill("0");
      await settle(page, 300);
      log(`[${width}] amount 0: ${JSON.stringify(await page.getByRole("alert").first().innerText().catch(() => "none"))}`);
      await amount.fill("99999");
      await settle(page, 300);
      log(`[${width}] amount over: ${JSON.stringify(await page.locator(".pay-record__warn").innerText().catch(() => "none"))}`);
      await amount.fill("500");
      await page.getByLabel("Reference").fill("BATCHJ-500");
      // A partial amount needs its reason (the platform's rule; not in the export).
      await page.getByLabel("Why is it different from what is outstanding?").fill("Part of the month, batch J check.");
      const url = page.url();
      await page.getByRole("button", { name: "Record payment" }).click();
      await page.waitForURL((u) => u.href !== url, { timeout: 10000 }).catch(() => undefined);
      await settle(page, 1000);
      const alert = await page.getByRole("alert").first().innerText().catch(() => "");
      log(`[${width}] saved: url=${page.url().replace(APP, "")} alert=${JSON.stringify(alert)}`);
      await page.reload({ waitUntil: "networkidle" });
      await settle(page, 800);
      const body = await page.locator("main").innerText();
      log(`[${width}] after reload shows BATCHJ-500: ${body.includes("BATCHJ-500")} / EGP 500.00: ${body.includes("EGP 500.00")}`);
      await page.screenshot({ path: join(OUT, `app-record-saved-${width}.png`) });
    }
    await context.close();
  }
};

/** Admin profile Overview: the contact form against the export, a save, a refusal. */
steps.contact = async (browser) => {
  const box = (page, loc) => loc.first().evaluate((el) => { const r = el.getBoundingClientRect(); return `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`; });
  for (const width of [1280, 1440]) {
    const { context: rc, ref } = await openExport(browser, ADMIN_EXPORT, width);
    await exportNav(ref, NAV.models).click();
    await exportTab(ref, "Active");
    await ref.locator(".ad > div:nth-child(2) button").filter({ hasText: "Sara Edrees" }).first().click();
    await settle(ref, 800);
    await ref.locator(".ad").screenshot({ path: join(OUT, `export-overview-${width}.png`) });
    const refCard = ref.locator(".ad div", { has: ref.locator("div", { hasText: /^Contact and shipping$/ }) }).last();
    log(`[${width}] export contact card: ${await box(ref, refCard)}`);
    log(`[${width}] export sizing card: ${await box(ref, ref.locator(".ad div", { has: ref.locator("div", { hasText: /^Sizing$/ }) }).last())}`);
    log(`[${width}] export input: ${JSON.stringify(await style(ref, refCard.locator("input")))}`);
    log(`[${width}] export label: ${JSON.stringify(await style(ref, refCard.locator("div", { hasText: /^Full name$/ })))}`);
    log(`[${width}] export save: ${JSON.stringify(await style(ref, refCard.locator("button")))}`);
    log(`[${width}] export sizing value: ${JSON.stringify(await style(ref, ref.locator(".ad span", { hasText: /^\d+ cm$/ })))}`);
    await rc.close();

    const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
    await page.goto(`${APP}/affiliates?q=Sara`, { waitUntil: "networkidle" });
    await settle(page, 800);
    await page.locator("tbody tr a").filter({ hasText: "Sara Edrees" }).first().click();
    await page.waitForLoadState("networkidle");
    await settle(page, 800);
    const url = page.url();
    await page.screenshot({ path: join(OUT, `app-overview-${width}.png`) });
    log(`[${width}] app contact card: ${await box(page, page.locator(".profile__contact"))}`);
    log(`[${width}] app side column: ${await box(page, page.locator(".profile__side"))}`);
    log(`[${width}] app input: ${JSON.stringify(await style(page, page.getByLabel("Full name")))}`);
    log(`[${width}] app label: ${JSON.stringify(await style(page, page.locator(".contact-form__label", { hasText: "Full name" })))}`);
    log(`[${width}] app save: ${JSON.stringify(await style(page, page.getByRole("button", { name: "Save details" })))}`);
    log(`[${width}] app sizing value: ${JSON.stringify(await style(page, page.locator(".profile__sizing-value")))}`);
    log(`[${width}] app start value: ${JSON.stringify(await style(page, page.locator(".profile__start-value .code, .profile__start-value .detail__note")))}`);
    log(`[${width}] app fields: ${JSON.stringify(await page.locator(".contact-form__label").allInnerTexts())} / sign-in is an input: ${await page.locator(".contact-form input[value='sara@example.com']").count() > 0}`);

    if (width === 1280) {
      const city = page.getByLabel("City");
      const before = await city.inputValue();
      await city.fill("Dokki");
      await page.getByRole("button", { name: "Save details" }).click();
      await page.getByRole("button", { name: "Saved" }).waitFor({ timeout: 8000 });
      await page.reload({ waitUntil: "networkidle" });
      await settle(page, 700);
      log(`[${width}] saved City "${before}" -> "Dokki"; after reload: "${await page.getByLabel("City").inputValue()}"`);

      await page.getByLabel("Full name").fill("Somebody Else");
      await page.getByRole("button", { name: "More address details" }).click();
      await page.getByLabel("Phone on the parcel").fill("12345");
      await page.getByRole("button", { name: "Save details" }).click();
      await settle(page, 900);
      log(`[${width}] refused: ${JSON.stringify(await page.getByRole("alert").first().innerText())} / typing kept: ${(await page.getByLabel("Full name").inputValue()) === "Somebody Else"}`);
      await page.screenshot({ path: join(OUT, `app-overview-refused-${width}.png`) });
      await page.reload({ waitUntil: "networkidle" });
      await settle(page, 700);
      log(`[${width}] after reload: name "${await page.getByLabel("Full name").inputValue()}", heading "${await page.locator("h1").first().innerText()}"`);
      await page.getByLabel("City").fill(before);
      await page.getByRole("button", { name: "Save details" }).click();
      await page.getByRole("button", { name: "Saved" }).waitFor({ timeout: 8000 });
      log(`[${width}] City put back to "${before}"`);
    }
    await context.close();
  }
};

const HANA = { email: "hana@example.com", password: "a-long-enough-password" };
const portalTab = (page, label) => page.locator(".pt").locator("button, a").filter({ hasText: new RegExp(`^${label}$`) }).last();

/** Items 5 and 6 at 390: Home's chips, and the guarantee behind its ⓘ. */
steps.portal = async (browser) => {
  const { context: rc, ref } = await openExport(browser, PORTAL_EXPORT, 390, ".pt");
  const refChips = ref.locator(".pt span", { hasText: /^\d+ (delivered|pending|failed delivery)$/ });
  log(`[390] export chips: ${JSON.stringify(await refChips.evaluateAll((els) => els.map((e) => `${e.tagName} ${e.textContent}`)))}`);
  log(`[390] export delivered chip: ${JSON.stringify(await style(ref, refChips))}`);
  await ref.locator(".pt").screenshot({ path: join(OUT, "export-portal-home-390.png") });
  await portalTab(ref, "Targets").click();
  await settle(ref, 700);
  const info = ref.locator(".pt button[aria-label='How the guaranteed minimum works']");
  log(`[390] export info button: ${JSON.stringify(await style(ref, info))}`);
  await info.click();
  await settle(ref, 400);
  await ref.locator(".pt").screenshot({ path: join(OUT, "export-portal-targets-open-390.png") });
  await rc.close();

  const { context, page } = await signIn(browser, MODEL, { width: 390, height: 844 });
  await page.goto(`${APP}/`, { waitUntil: "networkidle" });
  await settle(page, 800);
  const chips = page.locator(".portal-home__states > *");
  log(`[390] app chips: ${JSON.stringify(await chips.evaluateAll((els) => els.map((e) => `${e.tagName} ${e.textContent}`)))}`);
  log(`[390] app delivered chip: ${JSON.stringify(await style(page, chips))}`);
  await page.screenshot({ path: join(OUT, "app-portal-home-390.png") });
  await page.goto(`${APP}/targets`, { waitUntil: "networkidle" });
  await settle(page, 700);
  log(`[390] Sara (commission) targets: guarantee row shown=${await page.locator(".mytargets__guarantee").count() > 0}`);
  await context.close();

  const { context: hc, page: hana } = await signIn(browser, HANA, { width: 390, height: 844 });
  await hana.goto(`${APP}/targets`, { waitUntil: "networkidle" });
  await settle(hana, 700);
  const button = hana.getByRole("button", { name: "How the guaranteed minimum works" });
  log(`[390] Hana (guarantee): sentence shown before tap=${await hana.locator(".mytargets__pay").count() > 0}; button ${JSON.stringify(await style(hana, button))}`);
  await button.click();
  await settle(hana, 300);
  log(`[390] after tap: expanded=${await button.getAttribute("aria-expanded")} sentence=${JSON.stringify(await hana.locator(".mytargets__pay").innerText())}`);
  await hana.screenshot({ path: join(OUT, "app-portal-targets-open-390.png") });
  await hc.close();
};

/** Item 11: the switches save and survive a reload; Home obeys; the trail reads as sentences. */
steps.settings = async (browser) => {
  for (const width of [1280, 1440]) {
    const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
    await page.goto(`${APP}/settings?section=appearance`, { waitUntil: "networkidle" });
    await settle(page, 700);
    const notices = page.getByRole("switch", { name: "Show pop-up notices on Home" });
    const weekly = page.getByRole("switch", { name: "Weekly reminder to record achieved content" });
    log(`[${width}] switches: notices=${await notices.getAttribute("aria-checked")} weekly=${await weekly.getAttribute("aria-checked")}`);
    log(`[${width}] app switch row: ${JSON.stringify(await style(page, notices))}`);
    log(`[${width}] app track: ${JSON.stringify(await style(page, page.locator(".settings__track")))}`);
    await page.screenshot({ path: join(OUT, `app-appearance-${width}.png`) });

    if (width === 1280) {
      // Refused by the server: the switch stays where it was.
      await page.route("**/api/staff/me/preferences", (route) =>
        route.request().method() === "PUT" ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "The server is having a moment." }) }) : route.continue());
      await weekly.click();
      await settle(page, 500);
      log(`[${width}] refused: alert=${JSON.stringify(await page.getByRole("alert").first().innerText())} weekly still=${await weekly.getAttribute("aria-checked")}`);
      await page.unroute("**/api/staff/me/preferences");

      await notices.click();
      await settle(page, 600);
      await page.reload({ waitUntil: "networkidle" });
      await settle(page, 700);
      log(`[${width}] notices off, after reload: ${await page.getByRole("switch", { name: "Show pop-up notices on Home" }).getAttribute("aria-checked")}`);
      await page.screenshot({ path: join(OUT, `app-appearance-off-${width}.png`) });

      await page.goto(`${APP}/`, { waitUntil: "networkidle" });
      await settle(page, 800);
      log(`[${width}] Home with notices off: cards=${await page.locator(".overview__notice").count()} line=${JSON.stringify(await page.locator(".overview__hidden").innerText().catch(() => ""))}`);
      await page.screenshot({ path: join(OUT, `app-home-notices-off-${width}.png`) });
      await page.locator(".overview__hidden button", { hasText: "Show" }).click();
      await settle(page, 400);
      log(`[${width}] after Show: cards=${await page.locator(".overview__notice").count()}`);

      await page.goto(`${APP}/settings?section=appearance`, { waitUntil: "networkidle" });
      await settle(page, 600);
      await page.getByRole("switch", { name: "Show pop-up notices on Home" }).click();
      await settle(page, 600);
      log(`[${width}] put back on: ${await page.getByRole("switch", { name: "Show pop-up notices on Home" }).getAttribute("aria-checked")}`);
    }

    await page.goto(`${APP}/settings?section=advanced`, { waitUntil: "networkidle" });
    await settle(page, 800);
    const rows = await page.locator(".settings__activity-row").evaluateAll((els) => els.slice(0, 8).map((e) => e.innerText.replace(/\n/g, " | ")));
    log(`[${width}] activity: ${JSON.stringify(rows)}`);
    log(`[${width}] app activity what: ${JSON.stringify(await style(page, page.locator(".settings__activity-what")))}`);
    log(`[${width}] app activity who: ${JSON.stringify(await style(page, page.locator(".settings__activity-who")))}`);
    await page.screenshot({ path: join(OUT, `app-reference-${width}.png`) });
    await context.close();

    const { context: rc, ref } = await openExport(browser, ADMIN_EXPORT, width);
    await exportNav(ref, NAV.settings).click();
    await settle(ref);
    await exportTab(ref, "Appearance");
    const refRow = ref.locator(".ad button", { hasText: "Show pop-up notices on Home" });
    log(`[${width}] export switch row: ${JSON.stringify(await style(ref, refRow))}`);
    await ref.locator(".ad").screenshot({ path: join(OUT, `export-appearance-${width}.png`) });
    await exportTab(ref, "Reference");
    const what = ref.locator(".ad div", { hasText: /^Recorded a payment of/ });
    log(`[${width}] export activity what: ${JSON.stringify(await style(ref, what))}`);
    await ref.locator(".ad").screenshot({ path: join(OUT, `export-reference-${width}.png`) });
    await rc.close();
  }
};

/** Item 12: roster and Products rows against the export's button rows. */
steps.rows = async (browser) => {
  const PHASE = process.env.PHASE || "after";
  for (const width of [1280, 1440]) {
    const { context: rc, ref } = await openExport(browser, ADMIN_EXPORT, width);
    for (const [nav, label] of [[NAV.models, "roster"], [NAV.products, "products"]]) {
      await exportNav(ref, nav).click();
      await settle(ref, 800);
      const row = ref.locator(".ad > div:nth-child(2) button").filter({ has: ref.locator("span", { hasText: /^\s*→\s*$/ }) }).first();
      const r = await row.evaluate((el) => {
        const pill = [...el.querySelectorAll("span")].find((s) => getComputedStyle(s).borderRadius === "999px");
        const name = el.querySelector("span span span") || el.querySelector("span span");
        const box = (e) => e ? `${Math.round(e.getBoundingClientRect().height)}px ${getComputedStyle(e).fontSize} ${getComputedStyle(e).fontFamily.split(",")[0]}` : null;
        return { row: Math.round(el.getBoundingClientRect().height), font: getComputedStyle(el).fontFamily.split(",")[0], pill: box(pill), pillText: pill?.textContent, name: box(name) };
      });
      log(`[${width}] export ${label} row: ${JSON.stringify(r)}`);
      if (PHASE === "after") await ref.locator(".ad").screenshot({ path: join(OUT, `export-${label}-${width}.png`) });
    }
    await rc.close();

    const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
    for (const [path, label, rowSel] of [["/affiliates", "roster", "tbody tr"], ["/products", "products", "tbody tr, .products__row"]]) {
      await page.goto(`${APP}${path}`, { waitUntil: "networkidle" });
      await settle(page, 800);
      const row = page.locator(rowSel).first();
      if (!(await row.count())) { log(`[${width}] app ${label}: no row found`); continue; }
      const r = await row.evaluate((el) => {
        const pill = el.querySelector(".pill, [class*=pill]");
        const name = el.querySelector("[class*=name]");
        const box = (e) => e ? `${Math.round(e.getBoundingClientRect().height)}px ${getComputedStyle(e).fontSize} ${getComputedStyle(e).fontFamily.split(",")[0]}` : null;
        return { row: Math.round(el.getBoundingClientRect().height), font: getComputedStyle(el).fontFamily.split(",")[0], pill: box(pill), pillText: pill?.textContent, name: box(name) };
      });
      log(`[${width}] app ${label} row (${PHASE}): ${JSON.stringify(r)}`);
      if (PHASE === "after") await page.screenshot({ path: join(OUT, `app-${label}-${width}.png`) });
    }
    log(`[${width}] roster layout toggle present (${PHASE}): ${await page.goto(`${APP}/affiliates`, { waitUntil: "networkidle" }).then(() => page.locator("input[name=roster-view]").count()) > 0}`);
    await context.close();
  }
};

/** Item 13: the Home chart's rule labels outside the plot, as the export. */
steps.chart = async (browser) => {
  const read = (page, card) => page.locator(card).first().evaluate((el) => {
    const c = el.getBoundingClientRect();
    const svg = el.querySelector("svg");
    const texts = [...svg.querySelectorAll("text")].map((t) => { const r = t.getBoundingClientRect(); return { t: t.textContent, left: Math.round(r.left - c.left), right: Math.round(r.right - c.left), top: Math.round(r.top - c.top) }; });
    const plot = [...svg.querySelectorAll("line")].map((l) => l.getBoundingClientRect()).sort((a, b) => a.left - b.left)[0];
    return { card: Math.round(c.width), plotLeft: plot ? Math.round(plot.left - c.left) : null, bars: svg.querySelectorAll("rect").length, rules: texts.filter((x) => !/^[A-Z][a-z]{2}$|^\d{1,2}$/.test(x.t) || x.left < (plot ? plot.left - c.left : 0)).slice(0, 3) };
  });
  for (const width of [1280, 1440]) {
    const { context: rc, ref } = await openExport(browser, ADMIN_EXPORT, width);
    await exportNav(ref, NAV.home).click();
    await settle(ref, 800);
    const refCard = ".ad div:has(> div > span:text-is('Sales generated, EGP per month'))";
    const r = await read(ref, refCard).catch((e) => ({ error: String(e).slice(0, 120) }));
    log(`[${width}] export chart: ${JSON.stringify(r)}`);
    await ref.locator(refCard).first().screenshot({ path: join(OUT, `export-home-chart-${width}.png`) }).catch(() => undefined);
    await rc.close();

    const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
    await page.goto(`${APP}/`, { waitUntil: "networkidle" });
    await settle(page, 900);
    log(`[${width}] app chart: ${JSON.stringify(await read(page, ".sales-year"))}`);
    await page.locator(".sales-year").screenshot({ path: join(OUT, `app-home-chart-${width}.png`) });
    await context.close();
  }
};

function previousMonth() {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const browser = await chromium.launch();
try {
  for (const name of process.argv.slice(2)) {
    if (!steps[name]) throw new Error(`no step ${name}`);
    log(`## ${name} - ${new Date().toISOString()}`);
    await steps[name](browser);
  }
} finally {
  await browser.close();
}
