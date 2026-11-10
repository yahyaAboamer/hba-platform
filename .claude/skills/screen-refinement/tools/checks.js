async page => {
  // Phone sweep at 360 / 390 / 430: sideways scroll, controls under 44px,
  // input text under 16px, the keyboard order from a starting control, and
  // console errors. Add screen-specific checks (dialog focus, field errors)
  // at the end, as the Payments version does:
  // docs/design-refinement/payments/tools/checks.js
  // Usage: playwright-cli -s=hba --raw run-code --filename=checks.js
  // ---- CONFIG ----
  const H = 'https://hba-platform-staging-staging.up.railway.app';
  const routes = [
    // '/department/screen',
  ];
  const skip = '.never-matches'; // selector for controls exempt by design (e.g. chip rows checked separately)
  const tabFrom = null;          // e.g. ['/department/screen', 'searchbox'] to record 6 tab stops
  // ----------------
  const errors = [];
  page.on('console', m => { if (m.type() === 'error' && !/418|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  const out = [];
  for (const w of [360, 390, 430]) {
    await page.setViewportSize({ width: w, height: 800 });
    for (const p of routes) {
      await page.goto(H + p); await page.waitForLoadState('networkidle'); await page.waitForTimeout(300);
      const r = await page.evaluate((skip) => {
        const sideways = document.documentElement.scrollWidth > window.innerWidth + 1;
        const visible = [...document.querySelectorAll('main a, main button, main input, main select, main textarea')]
          .filter(e => e.offsetParent !== null && !e.closest(skip) && !(e.type === 'file'));
        const small = visible.map(e => [e, e.getBoundingClientRect()])
          .filter(([e, b]) => b.height < 44 && !(e.matches('a') && getComputedStyle(e).display === 'inline'))
          .map(([e, b]) => (e.textContent || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 30) + ':' + Math.round(b.height));
        const tinyText = visible.filter(e => e.matches('input, select, textarea') && parseFloat(getComputedStyle(e).fontSize) < 16)
          .map(e => (e.getAttribute('aria-label') || e.name || e.tagName) + ':' + getComputedStyle(e).fontSize);
        return { sideways, small, tinyText };
      }, skip);
      out.push(`${w} ${p}: sideways=${r.sideways} under44=[${r.small.join(', ')}] inputUnder16=[${r.tinyText.join(', ')}]`);
    }
  }
  if (tabFrom) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(H + tabFrom[0]); await page.waitForLoadState('networkidle');
    await page.getByRole(tabFrom[1]).first().focus();
    const stops = [];
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press('Tab');
      stops.push(await page.evaluate(() => { const a = document.activeElement; const o = getComputedStyle(a);
        return (a.textContent || a.getAttribute('aria-label') || a.tagName).trim().slice(0, 24) + (o.outlineStyle !== 'none' || o.boxShadow !== 'none' ? ' [ring]' : ' [NO RING]'); }));
    }
    out.push('tab order: ' + stops.join(' -> '));
  }
  out.push('console errors: ' + (errors.length ? errors.join(' | ') : 0));
  return out.join('\n');
}
