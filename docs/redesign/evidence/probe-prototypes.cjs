/* Source-only probes of the supplied mocks. No browser, network, app DB or Shopify.
 * This is review evidence, not production test coverage or an implementation engine.
 * Run from any directory: node path/to/evidence/probe-prototypes.cjs
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function run(file, probe) {
  const html = fs.readFileSync(path.join(__dirname, '..', 'designs', file), 'utf8');
  const match = html.match(/<script\b[^>]*type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/i);
  if (!match) throw new Error('No design logic found: ' + file);
  const sandbox = {
    DCLogic: class { setState(patch) {
      const p = typeof patch === 'function' ? patch(this.state) : patch;
      if (p) this.state = {...this.state, ...p};
    } },
    window: {setTimeout: () => 0}, navigator: {},
  };
  return vm.runInNewContext(match[1] + '\n' + probe, sandbox, {timeout: 2000});
}
const model = run('Affiliate Portal v3.dc.html', `
const c = new Component(); const out = [];
const ix = MONTHS.findIndex(m => m.state === 'approved'); c.state.monthIndex = ix;
const initialCommission = c.commissionOf(MONTHS[ix]);
const old = MONTHS[ix].orders.find(o => o.status === 'pending');
old.status = 'failed'; const changedCommission = c.commissionOf(MONTHS[ix]);
out.push({check:'Approved-but-unpaid month uses live commission', observed:initialCommission !== changedCommission, evidence:'isApprovedFixed excludes approved state', required:'Use frozen approval for approved and paid statements'});
c.state.monthIndex = 0; c.state.receiptFor = '2026-09'; c.state.stack = ['receipt'];
const receipt = c.renderVals().receiptMonth; c.renderVals().openEarnings();
out.push({check:'Receipt calculation context', receipt, earningsContext:MONTHS[c.state.monthIndex].label, correct:MONTHS[c.state.monthIndex].id === c.state.receiptFor});
const saved = c.state.form.instaLink;
c.renderVals().onInstaLink({target:{value:'https://ipn.eg/UNSAVED'}}); c.state.stack=[];
out.push({check:'Payout draft mutates shared form before Save', original:saved, draftStillInAccountForm:c.state.form.instaLink, required:'Separate persisted value from discardable draft'});
const removed=MONTHS.splice(1); c.state.monthIndex=0;
let v=c.renderVals();out.push({check:'One-month chart', finite:!/(NaN|Infinity)/.test(v.linePath), path:v.linePath});
MONTHS.push(...removed); MONTHS.forEach(m=>m.orders=[]); v=c.renderVals();
out.push({check:'All-zero chart', finite:!/(NaN|Infinity)/.test(v.linePath), path:v.linePath});
out;
`);
const admin = run('Admin Dashboard.dc.html', `
const c = new Component(); const out=[];
const m = MODELS.find(m => c.termsFor(m, CURRENT)?.type === 'guarantee');
if (!m) throw new Error('Missing guarantee fixture');
c.state.targets[m.id+'|'+CURRENT]={videos:1,stories:null,updated:null};
const pv=c.paymentVals({modelId:m.id,monthId:CURRENT});
out.push({check:'Guarantee approval when stories are unknown', targetsKnown:c.targetKnown(m,CURRENT), canApprove:pv.canApprove, required:'Both required outcomes must be known and valid before approval'});
out.push({check:'Fixture calendar ends in February 2027', yearOptions:c.termsVals({modelId:m.id}).tmYears.map(y=>y.label), monthsIn2027:MONTHS.filter(m=>m.year===2027).length, required:'Generate eligible and schedulable months from server dates, not fixture arrays'});
const roster=c.rosterModels(); const changed=roster[0];
const originalTerms=changed.terms;changed.terms=[];
MONTHS.filter(mo=>c.started(changed,mo.id)&&mIdx(mo.id)<=mIdx(CURRENT)).forEach(mo=>c.state.termsByMonth[changed.id+'|'+mo.id]={from:mo.id,type:'commission',rate:10});
const row=c.settingsVals().histRows.find(r=>r.name===changed.name);
out.push({check:'Historical readiness after selected-month terms supplied', model:changed.name, displayedState:row.state, required:'Read every selected month override and actual data coverage'});
changed.terms=originalTerms;
out;
`);
console.log(JSON.stringify({scope:'Targeted source logic only, not a rendered walkthrough or app test suite',model,admin},null,2));
