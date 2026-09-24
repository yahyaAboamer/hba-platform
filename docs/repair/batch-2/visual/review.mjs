/**
 * The visual and interaction review, in a browser of its own.
 *
 * Playwright drives a headless Chromium that Chrome's window manager never
 * hears about: no window is opened, restored, resized or stolen, and the
 * viewport is exactly what `newContext` says it is. That is the whole reason
 * this exists. `set-viewport.ps1` moved the *user's* Chrome to a real 1280 and
 * did it honestly, but it moved a window somebody was working in, and Chrome's
 * minimum width of ~500px put 390 out of reach entirely. Here 390 is a number
 * in a config object.
 *
 * ## What it captures, and why in pairs
 *
 * Each step captures the same state twice: the approved export, and the
 * running application. The export draws itself inside a fixed frame - `.ad`
 * at `width:1280px;height:900px` for the admin, `.pt` at 390x844 for the
 * portal - with its review toolbar *outside* that frame. Screenshotting the
 * frame element rather than the page excludes the toolbar by construction,
 * which is what "exclude the prototype's demonstration toolbar" asks for, and
 * gives the app the same content area to fill.
 *
 * ## And a digest, which is what actually finds the differences
 *
 * Looking at two screenshots finds gross layout breaks and nothing else. A
 * heading that says *Sales generated, EGP per month* against one that says
 * *Sales by month* is invisible at a glance and is exactly the kind of thing
 * this review is for. So every capture also writes a JSON digest - headings,
 * button and tab labels, every money string, the font and colour of the
 * heading and body - and `compare.mjs` diffs them.
 *
 * Usage:
 *   node review.mjs            # everything
 *   node review.mjs admin      # admin only
 *   node review.mjs portal     # portal only
 *   node review.mjs <step-id>  # one step
 */

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * `playwright-core` is **not** a dependency of this repository and must not
 * become one: it exists for one review, the frontend ships without it, and a
 * package in `frontend/package.json` that no build step uses is a package
 * somebody upgrades for no reason. So it is installed outside the tree and
 * pointed at:
 *
 *     npm install --prefix <scratch> playwright-core@1.58.0
 *     PLAYWRIGHT=<scratch>/node_modules/playwright-core/index.js node review.mjs
 *
 * **1.58.0 exactly.** Playwright pins a Chromium revision and refuses one it
 * did not download; 1.58.0 is the version whose revision 1208 is already in
 * this machine's `ms-playwright` cache, so the review needs no download at
 * all. Any other version starts by fetching 150MB.
 */
const playwright = await import(
  process.env.PLAYWRIGHT
    ? pathToFileURL(process.env.PLAYWRIGHT).href
    : "playwright-core"
);
// CommonJS reached by URL arrives under `default`; by package name it does not.
const { chromium } = playwright.chromium ? playwright : playwright.default;

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = join(HERE, "shots");
const APP = process.env.APP_URL || "http://127.0.0.1:8123";
const EXPORTS = process.env.EXPORT_URL || "http://127.0.0.1:8899";
const ADMIN_EXPORT = `${EXPORTS}/Admin%20Dashboard.dc.html`;
const PORTAL_EXPORT = `${EXPORTS}/Affiliate%20Portal%20v3.dc.html`;

const OWNER = { email: "owner@example.com", password: "a-long-enough-password" };
const MODEL = { email: "sara@example.com", password: "a-long-enough-password" };

/** The admin frame is 900 tall in the export; the phone frame is 844. */
const ADMIN_HEIGHT = 900;
const PHONE_HEIGHT = 844;

const settle = (page, ms = 550) => page.waitForTimeout(ms);

/** The month before this one, in the platform's `YYYY-MM`. */
const PREVIOUS_MONTH = (() => {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
})();

/**
 * The sidebar's nav buttons, in the export's own order.
 *
 * Every `ref` step goes through here, and it first closes whatever the last
 * step left open. The prototype keeps its state between steps exactly as a
 * real app does: a step that opened the *Record payment* sheet leaves it over
 * the sidebar, and the next step's nav click waits thirty seconds for a
 * button it can see and cannot reach. Escape, then click.
 */
const exportNav = (page, index) => {
  const button = page.locator(".ad > div:first-child button").nth(index);
  return {
    async click() {
      await page.keyboard.press("Escape");
      await settle(page, 200);
      await button.click({ timeout: 8000 }).catch(async () => {
        // Some sheets close on their own X rather than on Escape.
        await page.locator(".ad button", { hasText: /^[✕×]$/ }).first().click();
        await settle(page, 250);
        await button.click({ timeout: 8000 });
      });
    },
  };
};

const NAV = { home: 0, models: 1, products: 2, targets: 3, payments: 4, settings: 5 };

/**
 * A subtab **in the main pane**, never in the sidebar.
 *
 * The scope matters more than it looks. `.ad button` with the text *Payments*
 * matches the sidebar's nav item first, so `exportTab("Payments")` on a
 * model's page quietly navigated to the payments desk, and the review compared
 * one model's payment history against the whole desk - two screens that share
 * a word. Same trap for *Targets*.
 */
const exportMain = (page) => page.locator(".ad > div:nth-child(2)");

async function exportTab(page, label) {
  await exportMain(page)
    .locator("button")
    .filter({ hasText: new RegExp(`^\\s*${label}`) })
    .first()
    .click();
  await settle(page);
}

/**
 * What the page says, in a form two pages can be compared in.
 *
 * Deliberately *not* a DOM dump. Two implementations of the same design will
 * never share a tree, and diffing one would report nothing but noise. What has
 * to agree is the writing, the figures, the type and the colour.
 */
async function digest(page, selector) {
  return page.evaluate((sel) => {
    const root = sel ? document.querySelector(sel) : document.body;
    if (!root) return { missing: sel };
    const text = (el) => (el.textContent || "").replace(/\s+/g, " ").trim();
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const money = new Set();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      for (const hit of (node.nodeValue || "").matchAll(/(?:EGP|E£)\s?[\d,]+(?:\.\d\d)?/g)) {
        money.add(hit[0].replace(/\s+/g, " "));
      }
    }
    const typeOf = (el) => {
      if (!el) return null;
      const s = getComputedStyle(el);
      return {
        family: s.fontFamily.split(",")[0].replace(/["']/g, ""),
        size: s.fontSize,
        weight: s.fontWeight,
        colour: s.color,
      };
    };
    const firstHeading = [...root.querySelectorAll("h1,h2,h3,h4")].find(visible);

    // **Every visible line, in document order, however it is marked up.**
    //
    // The export writes its section titles as styled `div`s and its row
    // actions as `button`s; the app writes the first as `h2` and the second
    // as react-router `Link`s. Comparing `h2` to `h2` reports a difference on
    // every panel and finds nothing real, so what is compared is the writing.
    //
    // **`innerText`, not a walk of the text nodes.** The first version of
    // this joined each element's own text children with a space and produced
    // two false findings in its first run: the export's single string
    // `"1–12 of 19"` against the app's `{a}–{b} of {c}`, which is five
    // text nodes and came back as `1 – 12 of 19`; and `Open {{ monthLabel }}
    // in Payments →` against the same sentence with the month in a span,
    // which came back as `Open in Payments →`. Both were reported as wording
    // differences and neither was one. `innerText` is what the browser
    // renders, line by line, and two pages that read the same produce the
    // same lines whatever their markup.
    const runs = root.innerText
      .split(/\r?\n/)
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean);

    return {
      runs,
      headings: [...root.querySelectorAll("h1,h2,h3,h4")]
        .filter(visible)
        .map(text)
        .filter(Boolean),
      // **A segmented control counts as a control.** The export builds its
      // *Sales / Uses* switch and its theme switch from radio `<label>`s and
      // the app builds the same thing from `button`s, so a selector that
      // knows only about buttons reports the app as having two controls the
      // design does not - when the design has exactly those two.
      buttons: [
        ...root.querySelectorAll(
          "button,a,[role=button],[role=tab],label:has(input[type=radio])",
        ),
      ]
        .filter(visible)
        .map(text)
        .filter(Boolean),
      labels: [...root.querySelectorAll("label,th,dt,legend")]
        .filter(visible)
        .map(text)
        .filter(Boolean),
      money: [...money].sort(),
      heading: typeOf(firstHeading),
      body: typeOf(root),
      background: getComputedStyle(root).backgroundColor,
      scrollHeight: root.scrollHeight,
      clientHeight: root.clientHeight,
      // **The width it was actually taken at, read in the same batch as the
      // shutter.** The filename says 1280 because the config said 1280; this
      // says 1280 because the page did. Window-driven captures were renamed
      // after the fact for exactly this reason, and a digest that cannot
      // evidence its own width is a digest somebody has to trust.
      viewport: {
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        devicePixelRatio: window.devicePixelRatio,
        frame: sel ? Math.round(root.getBoundingClientRect().width) : null,
      },
    };
  }, selector);
}


/**
 * A step already captured on both sides is skipped, unless `FORCE=1`.
 *
 * This machine has 7.9GB and Docker holds a fifth of it; a headless Chromium
 * plus the app plus the export server is enough for the watchdog to reach for
 * a background job, and it did - twice, mid-run. Resumability is what makes
 * that cost one step instead of the whole sweep, exactly as it does for the
 * pytest runner. It also makes re-running after a fix cheap: delete the two
 * files for the screen you changed and run again.
 */
function alreadyCaptured(id, width) {
  if (process.env.FORCE === "1") return false;
  return (
    existsSync(join(SHOTS, "export", `${id}-${width}.png`)) &&
    existsSync(join(SHOTS, "app", `${id}-${width}.png`))
  );
}

async function capture(page, { side, id, width, selector, digestSelector }) {
  const dir = join(SHOTS, side);
  mkdirSync(dir, { recursive: true });
  const stem = join(dir, `${id}-${width}`);
  const target = selector ? page.locator(selector).first() : page;
  await target.screenshot({ path: `${stem}.png` });
  const d = await digest(page, digestSelector ?? selector);
  writeFileSync(`${stem}.json`, JSON.stringify(d, null, 1), "utf8");
  return d;
}

/** Sign in once and keep the cookies; every later context reuses them. */
async function signIn(browser, who, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(`${APP}/sign-in`, { waitUntil: "domcontentloaded" });
  await page.fill("input[type=email]", who.email);
  await page.fill("input[type=password]", who.password);
  await page.click("button[type=submit]");
  await page.waitForURL((url) => !url.pathname.startsWith("/sign-in"), { timeout: 15000 });
  await settle(page, 1200);
  return { context, page };
}

/** A subtab in the running application, by the word on it. */
async function appTab(page, label) {
  // `main` for the same reason `exportMain` exists: the sidebar owns the words
  // *Targets* and *Payments* too, and it comes first in the document.
  const scope = (await page.locator("main").count()) ? page.locator("main") : page.locator("body");
  await scope
    .getByRole("button", { name: new RegExp(`^${label}`) })
    .first()
    .click();
  await settle(page);
}

async function openSettings(page, section) {
  await page.goto(`${APP}/settings`, { waitUntil: "networkidle" });
  await appTab(page, section);
}

/**
 * The desk on the month before the working one.
 *
 * The working month is *awaiting approval* from end to end by construction,
 * so approved, partly paid and fully paid - three of the five states the
 * design draws - only exist on a month somebody has already agreed. The
 * month control is a grid the owner asked for rather than a `<select>`, and
 * the screen reads `?month=` anyway, which is both shorter and exactly what
 * the *Open in Payments* links on Home use.
 */
async function openPreviousMonth(page) {
  const previous = process.env.PREVIOUS_MONTH || PREVIOUS_MONTH;
  await page.goto(`${APP}/payments?month=${previous}`, { waitUntil: "networkidle" });
  await settle(page, 900);
}

/**
 * **Sara Edrees**, on both sides.
 *
 * It opened whoever the roster sorted first, which was Aya Sherif - the model
 * seeded with no terms at all - against the export's Sara, who has two
 * arrangements and a full history. Every panel differed and not one of the
 * differences was the design's.
 */
async function openFirstModel(page) {
  // Through the roster's own search, because the roster pages at twelve and
  // S is on the second page - which is the pagination working, not a problem.
  await page.goto(`${APP}/affiliates?q=Sara`, { waitUntil: "networkidle" });
  await settle(page, 800);
  await page.locator("tbody tr a").filter({ hasText: "Sara Edrees" }).first().click();
  await page.waitForLoadState("networkidle");
  await settle(page, 700);
}

async function openExportModel(page) {
  await exportNav(page, NAV.models).click();
  await exportTab(page, "Active");
  await exportMain(page).locator("button").filter({ hasText: "Sara Edrees" }).first().click();
  await settle(page);
}

// ── the steps ───────────────────────────────────────────────────────────────
//
// `app` drives the running application; `ref` drives the export. Both start
// from a signed-in page already on the dashboard, so a step that only changes
// section is two lines.

const admin = [
  {
    id: "home",
    app: async (p) => { await p.goto(`${APP}/`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await exportNav(p, NAV.home).click(); },
  },
  {
    id: "models-active",
    app: async (p) => { await p.goto(`${APP}/affiliates`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await exportNav(p, NAV.models).click(); },
  },
  {
    id: "models-applications",
    app: async (p) => {
      await p.goto(`${APP}/affiliates`, { waitUntil: "networkidle" });
      await p.getByRole("button", { name: /^Applications/ }).first().click();
    },
    ref: async (p) => { await exportNav(p, NAV.models).click(); await exportTab(p, "Applications"); },
  },
  {
    id: "models-invitations",
    app: async (p) => {
      await p.goto(`${APP}/affiliates`, { waitUntil: "networkidle" });
      await p.getByRole("button", { name: /^Invitations/ }).first().click();
    },
    ref: async (p) => { await exportNav(p, NAV.models).click(); await exportTab(p, "Invitations"); },
  },
  {
    id: "models-inactive",
    app: async (p) => {
      await p.goto(`${APP}/affiliates`, { waitUntil: "networkidle" });
      await p.getByRole("button", { name: /^Inactive/ }).first().click();
    },
    ref: async (p) => { await exportNav(p, NAV.models).click(); await exportTab(p, "Inactive"); },
  },
  {
    id: "products",
    app: async (p) => { await p.goto(`${APP}/products`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await exportNav(p, NAV.products).click(); },
  },
  {
    id: "targets",
    app: async (p) => { await p.goto(`${APP}/targets`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await exportNav(p, NAV.targets).click(); },
  },
  {
    id: "payments",
    app: async (p) => { await p.goto(`${APP}/payments`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await exportNav(p, NAV.payments).click(); },
  },
  {
    id: "products-all",
    app: async (p) => {
      await p.goto(`${APP}/products`, { waitUntil: "networkidle" });
      await p.getByRole("button", { name: /^All products/ }).first().click();
    },
    ref: async (p) => { await exportNav(p, NAV.products).click(); await exportTab(p, "All products"); },
  },
  {
    id: "products-requests",
    app: async (p) => {
      await p.goto(`${APP}/products`, { waitUntil: "networkidle" });
      await p.getByRole("button", { name: /requests/i }).first().click();
    },
    ref: async (p) => { await exportNav(p, NAV.products).click(); await exportTab(p, "Active requests"); },
  },

  // The payments desk, on the month that has money in it. The working month is
  // all *awaiting approval* by construction; every other state - approved,
  // partly paid, fully paid - only exists once a month has been agreed, which
  // is the month before. The export's fixture is already there, so this is the
  // step that makes the two comparable rather than a comparison of one state.
  {
    id: "payments-previous",
    app: async (p) => { await openPreviousMonth(p); },
    ref: async (p) => { await exportNav(p, NAV.payments).click(); },
  },
  {
    id: "payments-approved",
    app: async (p) => { await openPreviousMonth(p); await appTab(p, "Approved"); },
    ref: async (p) => { await exportNav(p, NAV.payments).click(); await exportTab(p, "Approved"); },
  },
  {
    id: "payments-partly-paid",
    app: async (p) => { await openPreviousMonth(p); await appTab(p, "Partly paid"); },
    ref: async (p) => { await exportNav(p, NAV.payments).click(); await exportTab(p, "Partly paid"); },
  },
  {
    id: "payments-fully-paid",
    app: async (p) => { await openPreviousMonth(p); await appTab(p, "Fully paid"); },
    ref: async (p) => { await exportNav(p, NAV.payments).click(); await exportTab(p, "Fully paid"); },
  },
  {
    id: "payments-no-transfer-due",
    app: async (p) => { await openPreviousMonth(p); await appTab(p, "No transfer due"); },
    ref: async (p) => { await exportNav(p, NAV.payments).click(); await exportTab(p, "No transfer due"); },
  },
  {
    id: "payment-detail",
    app: async (p) => {
      await openPreviousMonth(p);
      await appTab(p, "Fully paid");
      await p.getByRole("link", { name: /^Open$/ }).first().click();
      await p.waitForLoadState("networkidle");
      await p.locator("text=Loading…").waitFor({ state: "detached", timeout: 15000 })
        .catch(() => {});
      await settle(p, 800);
    },
    ref: async (p) => {
      await exportNav(p, NAV.payments).click();
      await exportTab(p, "All");
      await p.locator(".ad button", { hasText: /^Open$/ }).first().click();
    },
  },
  {
    id: "payment-record",
    app: async (p) => {
      await openPreviousMonth(p);
      await appTab(p, "Approved");
      await p.getByRole("link", { name: /^Record payment$/ }).first().click();
      await p.waitForLoadState("networkidle");
      // **Wait for the form, not for the spinner to go.** The sheet fetches
      // its balance after the route resolves, and waiting for `Loading…` to
      // detach resolves instantly when it has not appeared yet - which is how
      // the first capture of this screen was a screenshot of the word
      // "Loading…". Waiting for something that only exists when the data has
      // arrived cannot race it.
      await p.getByText("Amount transferred").first().waitFor({ timeout: 20000 });
      await settle(p, 600);
    },
    ref: async (p) => {
      await exportNav(p, NAV.payments).click();
      await exportTab(p, "All");
      await p.locator(".ad button", { hasText: /^Record payment$/ }).first().click();
    },
  },

  {
    id: "model-overview",
    app: async (p) => { await openFirstModel(p); },
    ref: async (p) => { await openExportModel(p); },
  },
  {
    id: "model-wardrobe",
    app: async (p) => { await openFirstModel(p); await appTab(p, "Wardrobe"); },
    ref: async (p) => { await openExportModel(p); await exportTab(p, "Wardrobe"); },
  },
  {
    id: "model-performance",
    app: async (p) => { await openFirstModel(p); await appTab(p, "Performance"); },
    ref: async (p) => { await openExportModel(p); await exportTab(p, "Performance"); },
  },
  {
    id: "model-targets",
    app: async (p) => { await openFirstModel(p); await appTab(p, "Targets"); },
    ref: async (p) => { await openExportModel(p); await exportTab(p, "Targets"); },
  },
  {
    id: "model-payments",
    app: async (p) => { await openFirstModel(p); await appTab(p, "Payments"); },
    ref: async (p) => { await openExportModel(p); await exportTab(p, "Payments"); },
  },

  {
    id: "settings-team",
    app: async (p) => { await p.goto(`${APP}/settings`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await exportNav(p, NAV.settings).click(); },
  },
  {
    id: "settings-shopify",
    app: async (p) => { await openSettings(p, "Shopify and sync"); },
    ref: async (p) => { await exportNav(p, NAV.settings).click(); await exportTab(p, "Shopify and sync"); },
  },
  {
    id: "settings-historical",
    app: async (p) => { await openSettings(p, "Historical setup"); },
    ref: async (p) => { await exportNav(p, NAV.settings).click(); await exportTab(p, "Historical setup"); },
  },
  {
    id: "settings-brand-codes",
    app: async (p) => { await openSettings(p, "Brand codes"); },
    ref: async (p) => { await exportNav(p, NAV.settings).click(); await exportTab(p, "Brand codes"); },
  },
  {
    id: "settings-appearance",
    app: async (p) => { await openSettings(p, "Appearance"); },
    ref: async (p) => { await exportNav(p, NAV.settings).click(); await exportTab(p, "Appearance"); },
  },
  {
    id: "settings-reference",
    app: async (p) => { await openSettings(p, "Reference"); },
    ref: async (p) => { await exportNav(p, NAV.settings).click(); await exportTab(p, "Reference"); },
  },

  // Popups and menus. The account menu and the invitation form are the two
  // the export draws; the app's own overlays are captured beside them.
  {
    id: "popup-account-menu",
    app: async (p) => {
      await p.goto(`${APP}/`, { waitUntil: "networkidle" });
      await p.locator("nav button, aside button").last().click();
    },
    ref: async (p) => {
      await exportNav(p, NAV.home).click();
      await p.locator(".ad > div:first-child button").nth(6).click();
    },
  },
  {
    id: "popup-invite-a-model",
    app: async (p) => {
      await p.goto(`${APP}/affiliates/invite`, { waitUntil: "networkidle" });
    },
    ref: async (p) => {
      await exportNav(p, NAV.models).click();
      await p.locator(".ad button", { hasText: /^Invite a model$/ }).first().click();
    },
  },
];

// ── the phone ───────────────────────────────────────────────────────────────
//
// 390 is where the window-driven approach ran out: Chrome will not make a
// window narrower than about 500px, so the model's half of the product had
// never actually been looked at at its own size. Here it is a number.

/** A tab on the portal's bottom bar, on either side. */
const portalTab = (page, label, inFrame) =>
  (inFrame ? page.locator(".pt") : page.locator("body"))
    .locator("button, a")
    .filter({ hasText: new RegExp(`^${label}$`) })
    .last();

/**
 * Back to the export's Home, from wherever the last step left it.
 *
 * **The tab bar is not on every screen.** The You sheet and the screens under
 * it replace it with a back arrow, which is the design working - and it meant
 * a step that started with "click Home" waited thirty seconds for a tab that
 * was not on the screen.
 */
async function portalHome(page) {
  for (let i = 0; i < 4; i++) {
    const back = page.locator(".pt button", { hasText: /^←/ });
    if (!(await back.count())) break;
    await back.first().click();
    await settle(page, 350);
  }
  await portalTab(page, "Home", true).click();
  await settle(page);
}

const portal = [
  {
    id: "portal-home",
    app: async (p) => { await p.goto(`${APP}/`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await portalHome(p); },
  },
  {
    id: "portal-orders",
    app: async (p) => { await p.goto(`${APP}/orders`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await portalHome(p); await portalTab(p, "Orders", true).click(); },
  },
  {
    id: "portal-wardrobe",
    app: async (p) => { await p.goto(`${APP}/wardrobe`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await portalHome(p); await portalTab(p, "Wardrobe", true).click(); },
  },
  {
    id: "portal-targets",
    app: async (p) => { await p.goto(`${APP}/targets`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await portalHome(p); await portalTab(p, "Targets", true).click(); },
  },
  {
    id: "portal-ranking",
    app: async (p) => { await p.goto(`${APP}/ranking`, { waitUntil: "networkidle" }); },
    ref: async (p) => { await portalHome(p); await portalTab(p, "Ranking", true).click(); },
  },
  {
    id: "portal-you",
    app: async (p) => { await p.goto(`${APP}/you`, { waitUntil: "networkidle" }); },
    ref: async (p) => {
      await portalHome(p);
      await p.locator('.pt button[aria-label="Your account"]').first().click();
    },
  },
  {
    id: "portal-payments",
    app: async (p) => { await p.goto(`${APP}/payments`, { waitUntil: "networkidle" }); },
    ref: async (p) => {
      await portalHome(p);
      await p.locator(".pt button", { hasText: "Payment history" }).first().click();
    },
  },
  {
    id: "portal-payment-details",
    app: async (p) => { await p.goto(`${APP}/you/payout`, { waitUntil: "networkidle" }); },
    ref: async (p) => {
      await portalHome(p);
      await p.locator('.pt button[aria-label="Your account"]').first().click();
      await settle(p);
      await p.locator(".pt button", { hasText: "Payment details" }).first().click();
    },
  },
  // **No `portal-month-picker` step here.** When this sweep was written the
  // app's control was a native `<select>`, whose list the operating system
  // draws outside the page. Batch E replaced it with the export's `Sep ▼`
  // button and in-page list; `shared-controls.mjs` captures both sides of it
  // open (`portal-month-open-390`) and a month chosen from it.
  {
    id: "portal-earnings",
    app: async (p) => { await p.goto(`${APP}/earnings`, { waitUntil: "networkidle" }); },
    ref: async (p) => {
      await portalHome(p);
      await p.locator(".pt button", { hasText: "How this adds up" }).first().click();
    },
  },
];

async function runPortal() {
  const browser = await chromium.launch({ headless: true });
  const width = 390;
  const results = [];
  const { context, page } = await signIn(browser, MODEL, { width, height: PHONE_HEIGHT });

  const refContext = await browser.newContext({
    viewport: { width: 900, height: PHONE_HEIGHT + 300 },
    deviceScaleFactor: 1,
  });
  const ref = await refContext.newPage();
  await ref.goto(PORTAL_EXPORT, { waitUntil: "networkidle" });
  await settle(ref, 1200);
  const frameWidth = await ref.evaluate(
    () => document.querySelector(".pt").getBoundingClientRect().width
  );
  if (frameWidth !== width) throw new Error(`portal frame is ${frameWidth}px, expected 390`);

  for (const step of portal) {
    if (alreadyCaptured(step.id, width)) {
      console.log(`skipped ${step.id} @ ${width} (already captured)`);
      continue;
    }
    try {
      await step.ref(ref);
      await settle(ref);
      await capture(ref, { side: "export", id: step.id, width, selector: ".pt" });
      await step.app(page);
      await settle(page, 900);
      // **The picture is the whole 390-wide viewport; the digest is the
      // portal's own root.** `main.affiliate` is where `data-theme` lands -
      // the screens a model sees before the layout exists would otherwise
      // paint light for a frame - so a digest taken from `body` reads the
      // document's default background and reports a theme difference that is
      // not on the screen.
      await capture(page, {
        side: "app",
        id: step.id,
        width,
        digestSelector: "main.affiliate",
      });
      results.push({ id: step.id, width, ok: true });
      console.log(`captured ${step.id} @ ${width}`);
    } catch (error) {
      results.push({ id: step.id, width, ok: false, error: String(error).slice(0, 300) });
      console.log(`FAILED ${step.id} @ ${width}: ${String(error).slice(0, 160)}`);
    }
  }
  await refContext.close();
  await context.close();
  await browser.close();
  return results;
}

async function run(which) {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  const widths = [1280, 1440];

  for (const width of widths) {
    const viewport = { width, height: ADMIN_HEIGHT };
    const { context, page } = await signIn(browser, OWNER, viewport);

    const refContext = await browser.newContext({
      viewport: { width: width + 220, height: ADMIN_HEIGHT + 260 },
      deviceScaleFactor: 1,
    });
    const ref = await refContext.newPage();
    await ref.goto(ADMIN_EXPORT, { waitUntil: "networkidle" });
    await settle(ref, 1200);
    if (width === 1440) {
      // The radio itself is visually hidden behind the segmented control's
      // own styling, so the label is what a person clicks and what this does.
      await ref.locator("label.seg-opt", { hasText: "1440" }).first().click();
      await settle(ref, 700);
    }
    const frameWidth = await ref.evaluate(
      () => document.querySelector(".ad").getBoundingClientRect().width
    );
    if (frameWidth !== width) {
      throw new Error(`export frame is ${frameWidth}px, expected ${width}px`);
    }

    for (const step of admin) {
      if (which && which !== "admin" && which !== step.id) continue;
      if (alreadyCaptured(step.id, width)) {
        console.log(`skipped ${step.id} @ ${width} (already captured)`);
        continue;
      }
      try {
        await step.ref(ref);
        await settle(ref);
        const r = await capture(ref, { side: "export", id: step.id, width, selector: ".ad" });
        await step.app(page);
        await settle(page, 900);
        const a = await capture(page, { side: "app", id: step.id, width });
        results.push({ id: step.id, width, ok: true, refHeadings: r.headings, appHeadings: a.headings });
        console.log(`captured ${step.id} @ ${width}`);
      } catch (error) {
        results.push({ id: step.id, width, ok: false, error: String(error).slice(0, 300) });
        console.log(`FAILED ${step.id} @ ${width}: ${String(error).slice(0, 160)}`);
      }
    }
    await refContext.close();
    await context.close();
  }

  mkdirSync(SHOTS, { recursive: true });
  writeFileSync(join(SHOTS, "run.json"), JSON.stringify(results, null, 1), "utf8");
  await browser.close();
}

const which = process.argv[2];
if (which === "portal") {
  await runPortal();
} else if (which === "admin" || !which) {
  await run(which);
  if (!which) await runPortal();
} else {
  await run(which);
}
