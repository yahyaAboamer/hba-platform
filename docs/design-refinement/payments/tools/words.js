async page => {
  // Words on each Payments screen at 390px, the page chrome (sidebar, top bar) excluded.
  const H = 'https://hba-platform-staging-staging.up.railway.app/affiliates/payments';
  const M = '2026-10';
  const paths = [['list', `?month=${M}`], ['estimate', `/${M}/104`], ['send', `/${M}/101`], ['partial', `/${M}/102`],
    ['overpaid', `/${M}/103`], ['credited', `/${M}/106`], ['record', `/${M}/101/record`], ['transfer', `/${M}/102/receipts/9102`],
    ['reconcile', `/${M}/103/reconcile`], ['correction', `/${M}/102/correction`]];
  await page.setViewportSize({ width: 390, height: 844 });
  const out = [];
  for (const [name, p] of paths) {
    await page.goto(H + p); await page.waitForLoadState('networkidle'); await page.waitForTimeout(300);
    const r = await page.evaluate(() => {
      const main = document.querySelector('main') || document.body;
      const words = (main.innerText.match(/\S+/g) || []).length;
      return { words, height: Math.round(document.documentElement.scrollHeight) };
    });
    out.push(`${name}\t${r.words}\t${r.height}`);
  }
  return out.join('\n');
}
