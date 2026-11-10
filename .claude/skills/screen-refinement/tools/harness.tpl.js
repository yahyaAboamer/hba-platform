async page => {
  // Generic read-only state gallery (Option B in references/harness.md).
  // Serves the local build named by __WEB__ on the staging origin, passes
  // GETs through to staging's real API, injects fixtures for missing states,
  // and refuses every write with a 418. Edit the CONFIG block per screen.
  // Full worked example: docs/design-refinement/payments/tools/harness.tpl.js
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const WEB = '__WEB__';          // a built dist folder, or 'staging'
  const OUT = '__OUT__';
  const ONLY = __ONLY__;          // null or a list of shot names
  const SIZES = __SIZES__;        // e.g. [[390,844],[1440,900]]
  const THEME = '__THEME__';      // 'dark' or 'light'
  const H = 'https://hba-platform-staging-staging.up.railway.app';

  // ---- CONFIG -------------------------------------------------------------
  // One fixture per business fact. Derive every field from the server's own
  // formula (write the formula in a comment) and use the real enums.
  const FIXTURES = [
    // { id: 101, name: 'Example (test)', state: '...' },
  ];
  // Exact GET responses to replace: return a JSON body, or undefined to pass.
  const fake = (path, url) => {
    // let m; if ((m = path.match(/^\/api\/thing\/(\d+)$/))) { const f = FIXTURES.find(x => String(x.id) === m[1]); if (f) return { ...f }; }
    return undefined;
  };
  // Real GET responses to extend (append fixtures to a list, patch totals).
  const patch = async (path, body) => {
    // if (path === '/api/things') body.items = body.items.concat(FIXTURES);
    return body;
  };
  // [name, path, optional action]
  const shots = [
    // ['list', '/department/screen'],
    // ['list-error', '/department/screen?fail=1'],
    // ['dialog', '/department/screen/101', async () => { await page.getByRole('button', { name: /^Approve/ }).click(); }],
  ];
  // -------------------------------------------------------------------------

  await page.route(H + '/**', async route => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;
    if (p.startsWith('/api/')) {
      if (req.method() !== 'GET' && !p.startsWith('/api/auth'))
        return route.fulfill({ status: 418, json: { detail: 'Blocked by the review harness: nothing is written.' } });
      if (page.url().includes('fail=1') && !p.startsWith('/api/auth') && !p.startsWith('/api/me'))
        return route.fulfill({ status: 500, json: { detail: 'The service did not answer. Try again in a minute.' } });
      const f = fake(p, url);
      if (f !== undefined) return route.fulfill({ json: f });
      const res = await route.fetch();
      const type = res.headers()['content-type'] || '';
      if (!type.includes('json')) return route.fulfill({ response: res });
      return route.fulfill({ response: res, json: await patch(p, await res.json()) });
    }
    if (WEB === 'staging') return route.continue();
    if (p.startsWith('/assets/')) return route.fulfill({ path: WEB + p });
    if (/\.(png|svg|ico|webmanifest|txt|woff2?)$/.test(p)) return route.continue();
    return route.fulfill({ path: WEB + '/index.html', contentType: 'text/html' });
  });

  const done = [];
  for (const [w, h] of SIZES) {
    await page.setViewportSize({ width: w, height: h });
    for (const [name, path, act] of shots) {
      if (ONLY && !ONLY.includes(name)) continue;
      await page.goto(H + path); await page.waitForLoadState('networkidle');
      // A desktop window's 15px scrollbar would eat a phone viewport's width.
      await page.addStyleTag({ content: '::-webkit-scrollbar{width:0!important;height:0!important}' });
      // The theme, for this capture only (nothing is saved to the account).
      if (THEME === 'light') await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
      await page.waitForTimeout(500);
      if (act) { try { await act(); } catch (e) { done.push(name + ' act failed: ' + e.message.split('\n')[0]); } await page.waitForTimeout(400); }
      await page.screenshot({ path: `${OUT}/${name}-${w}${THEME === 'light' ? '-light' : ''}.png`, fullPage: true });
      done.push(`${name}-${w}`);
    }
  }
  return done.join('\n');
}
