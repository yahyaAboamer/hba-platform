async page => {
  // Density: words in <main> and page height per route at 390px (the sidebar
  // and top bar are excluded). Run before and after; put both in the journal.
  // Usage: playwright-cli -s=hba --raw run-code --filename=words.js
  // ---- CONFIG ----
  const H = 'https://hba-platform-staging-staging.up.railway.app';
  const routes = [
    // ['list', '/department/screen'],
  ];
  // ----------------
  await page.setViewportSize({ width: 390, height: 844 });
  const out = ['screen\twords\theight'];
  for (const [name, p] of routes) {
    await page.goto(H + p); await page.waitForLoadState('networkidle'); await page.waitForTimeout(300);
    const r = await page.evaluate(() => {
      const main = document.querySelector('main') || document.body;
      return { words: (main.innerText.match(/\S+/g) || []).length, height: Math.round(document.documentElement.scrollHeight) };
    });
    out.push(`${name}\t${r.words}\t${r.height}`);
  }
  return out.join('\n');
}
