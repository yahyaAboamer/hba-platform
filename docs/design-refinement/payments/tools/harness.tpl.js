async page => {
  // Payments state gallery. Serves the local build named by __WEB__ on the
  // staging origin, reads staging's real API, adds fictional models to
  // October 2026 so every state exists, and refuses every write.
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const WEB = '__WEB__';
  const OUT = '__OUT__';
  const ONLY = __ONLY__;          // null or a list of shot names
  const SIZES = __SIZES__;
  const THEME = '__THEME__';     // 'dark' (the default) or 'light'
  const H = 'https://hba-platform-staging-staging.up.railway.app';
  const M = '2026-10';
  const daysAgo = n => new Date(Date.now() - n * 864e5).toISOString();
  const card = (num) => ({ kind: 'instapay', title: 'InstaPay', rows: [
    { label: 'InstaPay number', value: num, copy: 'number' },
    { label: 'Payment link, as submitted', value: 'https://ipn.eg/S/example/instapay/TEST01', copy: 'link' }],
    link: 'https://ipn.eg/S/example/instapay/TEST01' });
  const dest = { method: 'instapay', bank_name: null, bank_account_holder: null, wallet_provider: null,
    instapay_address_url: '…T01', instapay_phone: '…000', bank_account_number: null, wallet_phone: null };
  const base = (id, name, extra) => Object.assign({ affiliate_id: id, name, status: 'active', month: M,
    terms: 'commission', destination: dest, destination_line: 'InstaPay · 01000000' + id,
    destination_card: card('01000000' + id), state: 'unpaid', payroll_snapshot_id: 900 + id, version: 1,
    obligation_piastres: 0, paid_piastres: 0, adjusted_piastres: 0, credited_piastres: 0, balance_piastres: 0,
    forecast_piastres: null, forecast_blockers: [], required_kind: 'approved', required_piastres: 0,
    destination_changed_at: null }, extra);
  const FAKE = [
    base(101, 'Mona Adel (test)', { obligation_piastres: 980000, balance_piastres: 980000, required_piastres: 980000, destination_changed_at: daysAgo(2) }),
    base(102, 'Nour Hassan (test)', { state: 'partially_paid', obligation_piastres: 1200000, paid_piastres: 500000, balance_piastres: 700000, required_piastres: 1200000 }),
    base(103, 'Hana Samir (test)', { state: 'overpaid', obligation_piastres: 800000, paid_piastres: 850000, balance_piastres: -50000, required_piastres: 850000 }),
    base(104, 'Laila Fathy (test)', { state: 'not_approved', required_kind: 'forecast', forecast_piastres: 640000, required_piastres: 640000, payroll_snapshot_id: undefined, version: undefined }),
    base(105, 'Rana Kamal (test)', { state: 'not_approved', terms: null, required_kind: 'unavailable', payroll_snapshot_id: undefined, destination: null, destination_line: null, destination_card: null, forecast_blockers: ['no_compensation_terms_for_this_month'] }),
    base(106, 'Dina Youssef (test)', { state: 'settled', obligation_piastres: 200000, credited_piastres: 200000, required_piastres: 0 }),
  ];
  const owes = (r) => r.state === 'not_approved' ? r.required_piastres : r.obligation_piastres;
  const statement = (r) => ({ affiliate_id: r.affiliate_id, name: r.name, month: M,
    basis: r.state === 'not_approved' ? 'estimate' : 'approved', policy: r.state === 'not_approved' ? null : 'pending_inclusive',
    version: r.state === 'not_approved' ? null : 1, approved_at: r.state === 'not_approved' ? null : '2026-11-02T09:00:00Z',
    compensation_type: r.terms, commission_rate_bp: r.terms ? 1000 : null,
    // An approved statement's total is the snapshot's obligation, exactly as
    // the server builds it - never the row's required figure, which on an
    // overpaid month is what was sent (this fixture had that wrong once: F2-1).
    counted_sales_piastres: owes(r) * 10, commission_piastres: owes(r), fixed_piastres: 0,
    guarantee_top_up_piastres: 0, bonus_piastres: 0, carried_piastres: 0, total_piastres: owes(r),
    guarantee: { base_amount_piastres: 0, target_known: false },
    blockers: r.affiliate_id === 105 ? ['no_compensation_terms_for_this_month'] : [],
    source_version: r.state === 'not_approved' && r.affiliate_id !== 105 ? 'test-fingerprint' : null });
  const history = (r) => ({ name: r.name, payments: r.paid_piastres > 0 ? (r.affiliate_id === 103 ? [
      { id: 9301, amount_piastres: 800000, occurred_at: '2026-11-03T12:00:00Z', reference: 'IPN-TEST-301', note: null, has_proof: false, destination: dest, allocations: [{ month: M, snapshot_id: 903, snapshot_version: 1, allocated_piastres: 800000 }] },
      { id: 9302, amount_piastres: 50000, occurred_at: '2026-11-04T12:00:00Z', reference: null, note: 'Sent twice by mistake', has_proof: false, destination: dest, allocations: [{ month: M, snapshot_id: 903, snapshot_version: 1, allocated_piastres: 50000 }] }]
    : [{ id: 9000 + r.affiliate_id, amount_piastres: r.paid_piastres, occurred_at: '2026-11-03T12:00:00Z', reference: 'IPN-TEST-' + r.affiliate_id, note: 'InstaPay limit, the rest follows', has_proof: false, destination: dest, allocations: [{ month: M, snapshot_id: 900 + r.affiliate_id, snapshot_version: 1, allocated_piastres: r.paid_piastres }] }]) : [] });
  const corrections = (r) => ({ affiliate_id: r.affiliate_id, name: r.name, outstanding_piastres: 0,
    corrections: r.affiliate_id === 102 ? [{ affiliate_id: 102, month: M, agreed_piastres: 1200000, now_piastres: 1080000,
      paid_piastres: 500000, recoverable_piastres: 120000, snapshot_version: 1, shortfall_piastres: 120000,
      resolved_piastres: 0, outstanding_piastres: 120000, review_reason: null, resolved: false }] : [] });
  const byId = Object.fromEntries(FAKE.map(r => [String(r.affiliate_id), r]));
  let failNext = null; // 'list' to serve a 500 on the desk list once
  page.__fail = v => { failNext = v; };

  await page.route(H + '/**', async route => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;
    if (p.startsWith('/api/')) {
      if (req.method() !== 'GET' && !p.startsWith('/api/auth')) return route.fulfill({ status: 418, json: { detail: 'Blocked by the review harness: nothing is written.' } });
      if (p === '/api/payments/' + M) {
        if (url.searchParams.has('fail') || page.url().includes('fail=1')) return route.fulfill({ status: 500, json: { detail: 'The payments service did not answer. Try again in a minute.' } });
        const res = await route.fetch(); const body = await res.json();
        body.affiliates = body.affiliates.concat(FAKE);
        const t = body.totals;
        for (const r of FAKE) { t.required_piastres += r.required_piastres; if (r.required_kind === 'forecast') t.forecast_piastres += r.required_piastres; if (r.required_kind === 'approved') t.approved_piastres += r.obligation_piastres; t.recorded_piastres += r.paid_piastres; if (r.balance_piastres > 0) { t.still_owed_piastres += r.balance_piastres; t.still_owed_affiliates += 1; } }
        return route.fulfill({ response: res, json: body });
      }
      let m;
      if ((m = p.match(/^\/api\/payroll\/2026-10\/statement\/(\d+)$/)) && byId[m[1]]) return route.fulfill({ json: statement(byId[m[1]]) });
      if ((m = p.match(/^\/api\/affiliates\/(\d+)\/payments$/)) && byId[m[1]]) return route.fulfill({ json: history(byId[m[1]]) });
      if ((m = p.match(/^\/api\/affiliates\/(\d+)\/corrections$/)) && byId[m[1]]) return route.fulfill({ json: corrections(byId[m[1]]) });
      return route.continue();
    }
    if (WEB === 'staging') return route.continue();
    if (p.startsWith('/assets/')) return route.fulfill({ path: WEB + p });
    if (/\.(png|svg|ico|webmanifest|txt|woff2?)$/.test(p)) return route.continue();
    return route.fulfill({ path: WEB + '/index.html', contentType: 'text/html' });
  });

  const P = '/affiliates/payments';
  const shots = [
    ['list', `${P}?month=${M}`],
    ['list-empty-filter', `${P}?month=${M}`, async () => { await page.getByRole('button', { name: /^Part(ly)? paid/ }).first().click().catch(() => {}); await page.getByRole('searchbox').fill('zzz'); }],
    ['list-error', `${P}?month=${M}&fail=1`],
    ['detail-estimate', `${P}/${M}/104`],
    ['detail-confirm', `${P}/${M}/104`, async () => { await page.getByRole('button', { name: /^Approve/ }).first().click(); }],
    ['detail-terms', `${P}/${M}/105`],
    ['detail-blocked-real', `${P}/${M}/2`],
    ['detail-send', `${P}/${M}/101`],
    ['detail-partial', `${P}/${M}/102`],
    ['detail-overpaid', `${P}/${M}/103`],
    ['detail-credited', `${P}/${M}/106`],
    ['detail-done-real', `${P}/${M}/1`],
    ['record', `${P}/${M}/101/record`],
    ['record-partial', `${P}/${M}/101/record`, async () => { const a = page.getByLabel(/^Amount/); await a.fill('5000'); await page.getByLabel(/Transfer date|When was it sent/).fill('2999-01-01'); }],
    ['record-error', `${P}/${M}/102/record`, async () => { await page.getByRole('button', { name: /^Record/ }).first().click(); await page.waitForTimeout(500); }],
    ['receipt', `${P}/${M}/102/receipts/9102`],
    ['receipt-real', `${P}/${M}/1/receipts/1`],
    ['reconcile', `${P}/${M}/103/reconcile`],
    ['reconcile-chosen', `${P}/${M}/103/reconcile`, async () => { await page.getByText(/^Count it against|^Take it off a later/).first().click(); }],
    ['correction', `${P}/${M}/102/correction`],
  ];
  const done = [];
  for (const [w, h] of SIZES) {
    await page.setViewportSize({ width: w, height: h });
    for (const [name, path, act] of shots) {
      if (ONLY && !ONLY.includes(name)) continue;
      await page.goto(H + path); await page.waitForLoadState('networkidle');
      // A desktop window's 15px scrollbar would eat a phone viewport's width.
      await page.addStyleTag({ content: '::-webkit-scrollbar{width:0!important;height:0!important}' });
      // The account's theme, overridden for this capture only (nothing is saved).
      if (THEME === 'light') await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
      await page.waitForTimeout(500);
      if (act) { try { await act(); } catch (e) { done.push(name + ' act failed: ' + e.message.split('\n')[0]); } await page.waitForTimeout(400); }
      await page.screenshot({ path: `${OUT}/${name}-${w}${THEME === 'light' ? '-light' : ''}.png`, fullPage: true });
      done.push(`${name}-${w}`);
    }
  }
  return done.join('\n');
}
