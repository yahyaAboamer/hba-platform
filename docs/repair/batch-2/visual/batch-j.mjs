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
