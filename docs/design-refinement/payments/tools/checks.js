async page => {
  const H = 'https://hba-platform-staging-staging.up.railway.app/affiliates/payments';
  const M = '2026-10';
  const errors = [];
  page.on('console', m => { if (m.type() === 'error' && !/418|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  const out = [];
  const paths = ['', `/${M}/101`, `/${M}/102`, `/${M}/103`, `/${M}/104`, `/${M}/2`, `/${M}/101/record`, `/${M}/102/receipts/9102`, `/${M}/103/reconcile`, `/${M}/102/correction`];
  for (const w of [360, 390, 430]) {
    await page.setViewportSize({ width: w, height: 800 });
    for (const p of paths) {
      await page.goto(H + (p || `?month=${M}`)); await page.waitForLoadState('networkidle'); await page.waitForTimeout(300);
      const r = await page.evaluate(() => {
        const sideways = document.documentElement.scrollWidth > window.innerWidth + 1;
        const small = [...document.querySelectorAll('main a, main button, main input, main select, main textarea, main label.pay-record__drop')]
          .filter(e => e.offsetParent !== null && !e.closest('.payments__filters'))
          .map(e => [e, e.getBoundingClientRect()])
          .filter(([e, b]) => b.height < 44 && !(e.matches('a') && getComputedStyle(e).display === 'inline'))
          .map(([e, b]) => (e.textContent || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 30) + ':' + Math.round(b.height));
        return { sideways, small };
      });
      out.push(`${w} ${p || 'list'}: sideways=${r.sideways} small=[${r.small.join(', ')}]`);
    }
  }
  // Keyboard: approve opens the question with focus on its act; Cancel returns focus.
  await page.goto(H + `/${M}/104`); await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: 'Approve this month' }).focus();
  await page.keyboard.press('Enter'); await page.waitForTimeout(200);
  out.push('focus after Approve: ' + await page.evaluate(() => document.activeElement.textContent));
  await page.keyboard.press('Tab'); await page.keyboard.press('Enter'); await page.waitForTimeout(200);
  out.push('focus after Cancel: ' + await page.evaluate(() => document.activeElement.textContent));
  // Record form: a future date marks the field and points at its message.
  await page.goto(H + `/${M}/101/record`); await page.waitForLoadState('networkidle');
  await page.getByLabel('Transfer date').fill('2999-01-01');
  out.push('date invalid: ' + await page.getByLabel('Transfer date').getAttribute('aria-invalid') + ' / ' + await page.getByLabel('Transfer date').getAttribute('aria-describedby'));
  // Any write is refused by the harness, and the form says so.
  await page.getByLabel('Transfer date').fill('2026-11-05');
  await page.getByRole('button', { name: 'Record payment' }).click(); await page.waitForTimeout(500);
  out.push('write result: ' + await page.locator('.pay-record__error').textContent().catch(() => 'none'));
  // The shared month picker: its size on a phone, and that the keyboard alone changes the month.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(H + `?month=${M}`); await page.waitForLoadState('networkidle');
  const picker = page.getByLabel('Month').first();
  out.push('month picker: ' + await picker.evaluate(e => e.tagName + ' ' + Math.round(e.getBoundingClientRect().height) + 'px'));
  await picker.focus(); await page.keyboard.press('ArrowUp'); await page.waitForTimeout(600);
  out.push('month after ArrowUp: ' + await picker.inputValue() + ' url=' + new URL(page.url()).search);
  // Keyboard order on the list: from the search box, the next stops are the first row's name and act.
  await page.goto(H + `?month=${M}`); await page.waitForLoadState('networkidle');
  await page.getByRole('searchbox').focus();
  const stops = [];
  for (let i = 0; i < 4; i++) { await page.keyboard.press('Tab'); stops.push(await page.evaluate(() => { const a = document.activeElement; const o = getComputedStyle(a); return a.textContent.trim().slice(0, 24) + (o.outlineStyle !== 'none' || o.boxShadow !== 'none' ? ' [ring]' : ' [NO RING]'); })); }
  out.push('tab from search: ' + stops.join(' -> '));
  out.push('console errors: ' + (errors.length ? errors.join(' | ') : 0));
  return out.join('\n');
}
