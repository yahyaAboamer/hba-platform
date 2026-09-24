/**
 * Batch E: shared typography, identity headers and month controls.
 *
 *     PLAYWRIGHT=<scratch>/node_modules/playwright-core/index.js \
 *       node shared-controls.mjs <before|after>
 *
 * Same set-up as `review.mjs` (see README.md): the app on 8123 against the
 * throwaway `hba_browser` database, the exports served on 8899. It writes to
 * `shots/batch-e/<phase>/` and never touches `shots/app` or `shots/export`.
 *
 * **Every picture waits for `document.fonts.ready`**, and then for Inter at
 * each weight the page uses, because a capture taken while the face is still
 * arriving is a picture of the fallback - which is exactly the difference this
 * batch is about.
 *
 * **The portal is captured as a viewport**, not a full page: a full-page shot
 * paints the fixed tab bar over whatever sits at that height, and it hides
 * whether anything is under the bar at all. The export is captured as its
 * `.pt` frame *below the simulated status bar* - the `9:41` and battery are
 * the prototype's phone, not the application, so the clip starts under them.
 *
 * Beside each picture is a `.json` of what matters here: the typography of
 * every text-bearing element in the header and the first screen, and the
 * geometry of the identity line and month control.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const playwright = await import(
  process.env.PLAYWRIGHT ? pathToFileURL(process.env.PLAYWRIGHT).href : "playwright-core"
);
const { chromium } = playwright.chromium ? playwright : playwright.default;

const HERE = dirname(fileURLToPath(import.meta.url));
const PHASE = process.argv[2] || "after";
const ONLY = process.argv[3] || "";
const OUT = join(HERE, "shots", "batch-e", PHASE);
mkdirSync(OUT, { recursive: true });

const APP = process.env.APP_URL || "http://127.0.0.1:8123";
const EXPORTS = process.env.EXPORT_URL || "http://127.0.0.1:8899";
const OWNER = { email: "owner@example.com", password: "a-long-enough-password" };
const MODEL = { email: "sara@example.com", password: "a-long-enough-password" };

/** The long case: a name and a code at the length a real roster produces. */
const LONG_NAME = "Mariam Abdelrahman El-Sayed Mostafa";
const LONG_CODE = "MARIAMELSAYED2026";

const settle = (page, ms = 500) => page.waitForTimeout(ms);

async function fontsSettled(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    for (const w of [400, 500, 600]) await document.fonts.load(`${w} 15px Inter`);
    await document.fonts.ready;
  });
  await settle(page, 250);
}

/**
 * Typography of every element that owns visible text, inside `root`.
 * Keyed by its text so the two sides can be joined where they say the same
 * thing; anything whose text differs is sample data or copy, not type.
 */
async function typography(page, root, limit = 60) {
  return page.evaluate(({ root, limit }) => {
    const base = document.querySelector(root) || document.body;
    const top = base.getBoundingClientRect().top;
    const out = [];
    for (const el of base.querySelectorAll("*")) {
      const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim();
      if (!own && !(el.tagName === "SELECT")) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height || r.top - top > 800) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      const text = el.tagName === "SELECT" ? `[select] ${el.selectedOptions[0]?.textContent ?? ""}` : own.replace(/\s+/g, " ").slice(0, 48);
      out.push({
        text,
        tag: el.tagName.toLowerCase(),
        size: cs.fontSize,
        weight: cs.fontWeight,
        lh: cs.lineHeight,
        ls: cs.letterSpacing,
        num: cs.fontVariantNumeric,
        fam: cs.fontFamily.split(",")[0],
        h: Math.round(r.height * 10) / 10,
        w: Math.round(r.width * 10) / 10,
        y: Math.round((r.top - top) * 10) / 10,
      });
      if (out.length >= limit) break;
    }
    return out;
  }, { root, limit });
}

/** The identity line and the month control, measured. */
async function header(page, sel) {
  return page.evaluate((sel) => {
    const q = (s) => (s ? document.querySelector(s) : null);
    const box = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60),
        x: Math.round(r.left * 10) / 10, y: Math.round(r.top * 10) / 10,
        w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
        truncated: el.scrollWidth > el.clientWidth + 0.5,
        size: cs.fontSize, weight: cs.fontWeight, lh: cs.lineHeight, num: cs.fontVariantNumeric,
      };
    };
    return Object.fromEntries(Object.entries(sel).map(([k, s]) => [k, box(q(s))]));
  }, sel);
}

function save(name, data) {
  writeFileSync(join(OUT, `${name}.json`), JSON.stringify(data, null, 1), "utf8");
}

async function shoot(page, name, opts = {}) {
  await fontsSettled(page);
  await page.screenshot({ path: join(OUT, `${name}.png`), ...opts });
  console.log(`  ${name}`);
}

async function signIn(browser, who, viewport, mobile) {
  const context = await browser.newContext({
    viewport, deviceScaleFactor: 1, ...(mobile ? { isMobile: true, hasTouch: true } : {}),
  });
  const page = await context.newPage();
  await page.goto(`${APP}/sign-in`, { waitUntil: "domcontentloaded" });
  await page.fill("input[type=email]", who.email);
  await page.fill("input[type=password]", who.password);
  await page.click("button[type=submit]");
  await page.waitForURL((url) => !url.pathname.startsWith("/sign-in"), { timeout: 15000 });
  await settle(page, 1000);
  return { context, page };
}

// ── The portal at 390 ───────────────────────────────────────────────────────

const PORTAL_HEAD = {
  name: ".phead__name", identity: ".phead__since", month: ".phead__month",
  avatar: ".phead__avatar", header: ".phead",
};
const EXPORT_HEAD = {
  name: ".pt > div:nth-child(2) > div:nth-child(2) > div:nth-child(1)",
  identity: ".pt > div:nth-child(2) > div:nth-child(2) > div:nth-child(2)",
  month: ".pt > div:nth-child(2) > button:last-child",
  avatar: ".pt > div:nth-child(2) > button:first-child",
  header: ".pt > div:nth-child(2)",
};

async function exportPortal(browser) {
  const context = await browser.newContext({ viewport: { width: 1100, height: 1300 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(`${EXPORTS}/Affiliate%20Portal%20v3.dc.html`, { waitUntil: "networkidle" });
  await fontsSettled(page);
  const frame = page.locator(".pt");
  const width = await frame.evaluate((el) => el.getBoundingClientRect().width);
  if (width !== 390) throw new Error(`portal frame is ${width}px, expected 390`);
  /** The frame under the simulated status bar: the application, only. */
  const clip = async () => {
    const f = await frame.boundingBox();
    const bar = await page.locator(".pt > div:first-child").boundingBox();
    return { x: f.x, y: bar.y + bar.height, width: f.width, height: f.height - bar.height };
  };
  const tab = (label) => frame.locator("button").filter({ hasText: new RegExp(`^${label}$`) }).last();

  const shots = [];
  for (const [id, go] of [
    ["portal-home", async () => { await tab("Home").click(); }],
    ["portal-orders", async () => { await tab("Orders").click(); }],
    ["portal-ranking", async () => { await tab("Ranking").click(); }],
  ]) {
    await go(); await settle(page, 400);
    await shoot(page, `export-${id}-390`, { clip: await clip() });
    save(`export-${id}-390`, {
      header: await header(page, EXPORT_HEAD),
      type: await typography(page, ".pt > div:nth-child(2)", 12)
        .then(async (h) => h.concat(await typography(page, ".pt > div:nth-last-child(2)", 60))),
    });
    shots.push(id);
  }
  // Order rows, measured: the batch-D gap (95px against 92px) was put down
  // to font metrics, and this batch is what tests that.
  await tab("Orders").click(); await settle(page, 400);
  save("export-portal-order-rows-390", {
    rows: await frame.evaluate((pt) => [...pt.querySelectorAll("button")]
      .filter((b) => /^#/.test(b.innerText.trim())).map((b) => Math.round(b.getBoundingClientRect().height * 10) / 10)),
  });
  // The control open, on Home, and one month chosen from it.
  await tab("Home").click(); await settle(page, 300);
  await page.locator(EXPORT_HEAD.month).click(); await settle(page, 300);
  await shoot(page, "export-portal-month-open-390", { clip: await clip() });
  save("export-portal-month-open-390", {
    options: await frame.evaluate((pt) => [...pt.querySelectorAll(":scope > div:nth-child(3) button")].map((b) => {
      const cs = getComputedStyle(b); const r = b.getBoundingClientRect();
      return { text: b.innerText.replace(/\s+/g, " "), h: r.height, size: cs.fontSize, bg: cs.backgroundColor };
    })),
  });
  await page.locator(".pt > div:nth-child(3) button").nth(2).click(); await settle(page, 300);
  await shoot(page, "export-portal-month-picked-390", { clip: await clip() });
  await context.close();
}

async function appPortal(browser) {
  const { context, page } = await signIn(browser, MODEL, { width: 390, height: 844 }, true);
  for (const [id, path] of [["portal-home", "/"], ["portal-orders", "/orders"], ["portal-ranking", "/ranking"]]) {
    await page.goto(`${APP}${path}`, { waitUntil: "networkidle" }); await settle(page, 600);
    await shoot(page, `app-${id}-390`);
    save(`app-${id}-390`, {
      header: await header(page, PORTAL_HEAD),
      type: await typography(page, ".phead", 12)
        .then(async (h) => h.concat(await typography(page, ".portal__body", 60))),
    });
  }
  // Orders scrolled by a person, not a full-page shot: the tab bar stays
  // fixed and the last line must clear it.
  await page.goto(`${APP}/orders`, { waitUntil: "networkidle" }); await settle(page, 500);
  await page.mouse.wheel(0, 20000); await settle(page, 500);
  await shoot(page, "app-portal-orders-scrolled-end-390");
  save("app-portal-orders-scrolled-end-390", await page.evaluate(() => {
    const kids = [...document.querySelector(".portal__body").querySelectorAll("*")].filter((e) => e.getBoundingClientRect().height > 0);
    const last = Math.max(...kids.map((e) => e.getBoundingClientRect().bottom));
    return { lastContentBottom: Math.round(last), tabBarTop: Math.round(document.querySelector(".tabs").getBoundingClientRect().top), scrollY: window.scrollY, innerHeight };
  }));

  // The month control, open. A native select cannot be drawn open, so the
  // before-phase records its options instead.
  await page.goto(`${APP}/`, { waitUntil: "networkidle" }); await settle(page, 500);
  const trigger = page.locator(".phead__month");
  const tag = await trigger.evaluate((el) => el.tagName);
  if (tag === "BUTTON") {
    await trigger.click(); await settle(page, 700);
    await shoot(page, "app-portal-month-open-390");
    save("app-portal-month-open-390", {
      options: await page.$$eval(".pmonths button", (bs) => bs.map((b) => {
        const cs = getComputedStyle(b); const r = b.getBoundingClientRect();
        return { text: b.innerText.replace(/\s+/g, " "), h: r.height, size: cs.fontSize, bg: cs.backgroundColor };
      })),
    });
    await page.locator(".pmonths button").nth(1).click(); await settle(page, 900);
    await shoot(page, "app-portal-month-picked-390");
    save("app-portal-month-picked-390", { header: await header(page, PORTAL_HEAD) });
    // Opening the list, then a tab: the list must not follow her there.
    await trigger.click(); await settle(page, 300);
    await page.locator(".tabs__tab", { hasText: "Orders" }).click(); await settle(page, 700);
    save("app-portal-month-tab-closes-390", { listOpen: await page.locator(".pmonths").count() });
  } else {
    save("app-portal-month-open-390", {
      native: true,
      options: await trigger.evaluate((s) => [...s.options].map((o) => o.textContent)),
    });
  }

  // Orders in a month with a full list, chosen through the header's own
  // control, then scrolled to the end by a person: the header must stay at
  // the top and the last line must clear the tab bar.
  await page.goto(`${APP}/orders`, { waitUntil: "networkidle" }); await settle(page, 500);
  if (await page.locator("button.phead__month").count()) {
    await page.locator("button.phead__month").click(); await settle(page, 400);
    await page.locator(".pmonths button", { hasText: "July 2026" }).click(); await settle(page, 1000);
    await shoot(page, "app-portal-orders-july-390");
    const rows = await page.$$eval(".orders__row > button", (bs) => bs.map((b) => Math.round(b.getBoundingClientRect().height * 10) / 10));
    save("app-portal-orders-july-390", { rows });
    // July's list fits in 844px, so the scroll is checked on Home, which
    // does not: wheel to the end as a person would.
    await page.goto(`${APP}/`, { waitUntil: "networkidle" }); await settle(page, 700);
    await page.mouse.move(195, 500);
    for (let i = 0; i < 12; i++) { await page.mouse.wheel(0, 600); await settle(page, 120); }
    await settle(page, 500);
    await shoot(page, "app-portal-home-scrolled-end-390");
    save("app-portal-home-scrolled-end-390", {
      ...(await page.evaluate(() => {
        const body = document.querySelector(".portal__body");
        const kids = [...body.querySelectorAll("*")].filter((e) => e.getBoundingClientRect().height > 0);
        return {
          scrollY: Math.round(window.scrollY),
          headerTop: Math.round(document.querySelector(".phead").getBoundingClientRect().top),
          headerBottom: Math.round(document.querySelector(".phead").getBoundingClientRect().bottom),
          lastContentBottom: Math.round(Math.max(...kids.map((e) => e.getBoundingClientRect().bottom))),
          tabBarTop: Math.round(document.querySelector(".tabs").getBoundingClientRect().top),
          month: document.querySelector(".phead__month").innerText.replace(/\s+/g, " "),
        };
      })),
    });
  }

  // The long name and code, from the same screen with `/api/me` answering
  // for somebody whose name and code are at the length a real roster has.
  await page.route("**/api/me", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.name = LONG_NAME;
    if (body.codes?.[0]) body.codes[0].code = LONG_CODE;
    await route.fulfill({ response, json: body });
  });
  await page.goto(`${APP}/`, { waitUntil: "networkidle" }); await settle(page, 700);
  await shoot(page, "app-portal-home-long-390", { clip: { x: 0, y: 0, width: 390, height: 160 } });
  save("app-portal-home-long-390", { header: await header(page, PORTAL_HEAD) });
  await page.unroute("**/api/me");
  await context.close();
}

// ── The admin at 1280 and 1440 ─────────────────────────────────────────────

async function exportAdmin(browser, width) {
  const context = await browser.newContext({ viewport: { width: width + 220, height: 1160 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(`${EXPORTS}/Admin%20Dashboard.dc.html`, { waitUntil: "networkidle" });
  await fontsSettled(page);
  if (width === 1440) { await page.locator("label.seg-opt", { hasText: "1440" }).first().click(); await settle(page, 600); }
  const frame = page.locator(".ad");
  const fw = await frame.evaluate((el) => el.getBoundingClientRect().width);
  if (fw !== width) throw new Error(`export frame is ${fw}px, expected ${width}`);
  const nav = (i) => page.locator(".ad > div:first-child button").nth(i);
  const main = page.locator(".ad > div:nth-child(2)");
  const topbar = ".ad > div:nth-child(2) > div:first-child";

  for (const [id, go] of [
    ["admin-home", async () => { await nav(0).click(); }],
    ["admin-payments", async () => { await nav(4).click(); }],
    ["admin-targets", async () => { await nav(3).click(); }],
    ["admin-profile", async () => {
      await nav(1).click(); await settle(page, 300);
      await main.locator("button").filter({ hasText: /^\s*Active/ }).first().click(); await settle(page, 300);
      await main.locator("button").filter({ hasText: "Sara Edrees" }).first().click();
    }],
  ]) {
    await go(); await settle(page, 500);
    await shoot(page, `export-${id}-${width}`, { clip: await frame.boundingBox() });
    save(`export-${id}-${width}`, {
      topbar: await typography(page, topbar, 12),
      body: await typography(page, ".ad > div:nth-child(2) > div:nth-child(2)", 40),
      selects: await frame.evaluate((ad) => [...ad.querySelectorAll("select")].map((s) => {
        const r = s.getBoundingClientRect(); const cs = getComputedStyle(s);
        return { value: s.value, label: s.selectedOptions[0]?.textContent, options: s.options.length, h: r.height, w: r.width, size: cs.fontSize, x: r.left, y: r.top };
      })),
    });
  }
  await context.close();
}

async function appAdmin(browser, width) {
  const { context, page } = await signIn(browser, OWNER, { width, height: 900 });
  const measureSelects = () => page.evaluate(() => [...document.querySelectorAll("select, .month-picker__trigger")].map((s) => {
    const r = s.getBoundingClientRect(); const cs = getComputedStyle(s);
    return {
      tag: s.tagName, value: s.value ?? null,
      label: s.tagName === "SELECT" ? s.selectedOptions[0]?.textContent : s.innerText,
      options: s.tagName === "SELECT" ? [...s.options].map((o) => o.value) : null,
      h: r.height, w: r.width, size: cs.fontSize, x: r.left, y: r.top,
    };
  }));
  for (const [id, go] of [
    ["admin-home", async () => page.goto(`${APP}/`, { waitUntil: "networkidle" })],
    ["admin-payments", async () => page.goto(`${APP}/payments`, { waitUntil: "networkidle" })],
    ["admin-targets", async () => page.goto(`${APP}/targets`, { waitUntil: "networkidle" })],
    ["admin-orders", async () => page.goto(`${APP}/orders`, { waitUntil: "networkidle" })],
    ["admin-payroll", async () => page.goto(`${APP}/payroll`, { waitUntil: "networkidle" })],
    ["admin-profile", async () => {
      await page.goto(`${APP}/affiliates?q=Sara`, { waitUntil: "networkidle" }); await settle(page, 600);
      await page.locator("tbody tr a").filter({ hasText: "Sara Edrees" }).first().click();
      await page.waitForLoadState("networkidle");
    }],
  ]) {
    await go(); await settle(page, 800);
    await shoot(page, `app-${id}-${width}`);
    save(`app-${id}-${width}`, {
      topbar: await typography(page, ".page__head", 12),
      body: await typography(page, ".layout__main", 40),
      selects: await measureSelects(),
    });
  }

  // Choosing a month on the profile keeps the section and the address, and
  // Back returns to it (the export's back behaviour, and batch D's).
  const control = page.locator(".profile__month select");
  if (await control.count()) {
    const values = await control.evaluate((s) => [...s.options].map((o) => o.value));
    const pick = values[1];
    await page.locator(".profile__tab", { hasText: "Performance" }).click(); await settle(page, 600);
    await control.selectOption(pick); await settle(page, 900);
    const url = new URL(page.url());
    await shoot(page, `app-admin-profile-month-picked-${width}`);
    save(`app-admin-profile-month-picked-${width}`, {
      picked: pick, section: url.searchParams.get("section"), month: url.searchParams.get("month"),
      selected: await control.inputValue(),
    });
  }

  // The long name and code on the profile header.
  if (width === 1280) {
    await page.route(/\/api\/affiliates\/\d+(\?|$)/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.name = LONG_NAME;
      for (const c of body.codes ?? []) c.code = LONG_CODE;
      await route.fulfill({ response, json: body });
    });
    await page.reload({ waitUntil: "networkidle" }); await settle(page, 800);
    await shoot(page, `app-admin-profile-long-${width}`, { clip: { x: 0, y: 0, width, height: 260 } });
    await page.unroute(/\/api\/affiliates\/\d+(\?|$)/);
  }
  await context.close();
}

const browser = await chromium.launch({ headless: true });
try {
  if (!ONLY || ONLY === "portal") {
    console.log("export portal"); await exportPortal(browser);
    console.log("app portal"); await appPortal(browser);
  }
  if (!ONLY || ONLY === "admin") {
    for (const width of [1280, 1440]) {
      console.log(`export admin ${width}`); await exportAdmin(browser, width);
      console.log(`app admin ${width}`); await appAdmin(browser, width);
    }
  }
} finally {
  await browser.close();
}
