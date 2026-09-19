import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {FILES, parseCSV, csv, weeklyConflict, loadInstance, validate} from '../vendor/trackspace/engine.js';
import {requestedDiagnostics} from '../vendor/trackspace/request-diagnostics.mjs';
import {solve, finish} from '../vendor/trackspace/scheduler.mjs';

const python = process.argv[2];
const files = Object.fromEntries(await Promise.all(FILES.map(async f =>
  [f, await readFile(new URL('../PS1/01_data/'+f, import.meta.url), 'utf8')])));
const job = (workLocations, exclusion, access_type='C') =>
  ({workLocations, exclusion, project:{access_type}});
const a = job(['SEC:L:A_B:EB'], ['SEC:L:A_B:EB', 'PLAT:L:B:EB']);
const b = job(['SEC:L:C_D:EB'], ['SEC:L:C_D:EB', 'PLAT:L:B:EB']);
assert.equal(weeklyConflict(a,b,false), false, 'empty platform-buffer touch is exempt');
b.exclusion.push('SEC:L:A_B:EB');
assert.equal(weeklyConflict(a,b,true), true, 'different worksites with intersecting closures still clash');
const c = job(a.workLocations,a.exclusion);
assert.equal(weeklyConflict(a,c,true), false, 'legal direct sharing');
assert.equal(weeklyConflict(a,c,false), true, 'direct sharers must use the same possession');
c.project.access_type='PM';
assert.equal(weeklyConflict(a,c,true), true, 'PM cannot share');

const diagnostics=requestedDiagnostics(files,{python}).conflicts;
assert.equal(diagnostics.filter(c=>c.severity==='blocking').length,49);
assert.equal(diagnostics.filter(c=>c.severity==='coordination').length,124);
assert.equal(new Set(diagnostics.filter(c=>c.where).map(c=>c.week+'|'+c.where)).size,138);
assert.ok(diagnostics.some(c=>c.kind==='workfronts'));
assert.ok(diagnostics.some(c=>c.kind==='buffer'));

// A small real-network fixture has many tied but genuinely different weeks.
const table=parseCSV(files['08_ACTIVITY_DETAILS.csv']);
const row=table.rows.find(a=>a.activity_id==='A002');
files['08_ACTIVITY_DETAILS.csv']=csv([row],table.headers);
const model=loadInstance(files);
for(const scenario of ['A','B','C']) {
  const main=await solve(files,scenario,{python,timeLimitSeconds:3,slotLimit:2});
  assert.equal(main.feasible,true);
  assert.equal(main.alternatives.length,0,'main search must not automatically explore alternatives');
  const original=JSON.stringify(main);
  const extra=await solve(files,scenario,{python,timeLimitSeconds:3,slotLimit:2,
    alternativeOnly:true,seed:main.schedule,alternativeCount:3,alternativeSeconds:3});
  assert.equal(JSON.stringify(main),original,'alternative search changed the chosen result');
  const signature=c=>JSON.stringify(c.schedule.map(r=>[r.activity_id,r.week,r.eclo]).sort());
  assert.equal(new Set([main,extra,...extra.alternatives].map(signature)).size,4);
  assert.equal(extra.alternativeSearchStatus.length,3);
  const result=await solve(files,scenario,{python,timeLimitSeconds:3,alternativeCount:3,alternativeSeconds:3,slotLimit:2});
  assert.equal(result.feasible,true);
  assert.equal(result.alternatives.length,3);
  const candidates=[result,...result.alternatives];
  const signatures=new Set(candidates.map(c=>JSON.stringify(c.schedule.map(r=>[r.activity_id,r.week,r.eclo]).sort())));
  assert.equal(signatures.size,4,'group renumberings are not alternatives');
  for(const candidate of candidates) {
    assert.equal(validate(model,candidate.schedule,scenario).feasible,true);
    assert.equal(candidate.score,0);
    assert.equal(Object.keys(candidate.csvFiles).length,3);
  }
  assert.throws(()=>finish(model,{scenario,schedule:result.schedule,score:99}),/failed schedule or score validation/);
  assert.throws(()=>finish(model,{scenario,schedule:[{...result.schedule[0],week:0}],score:0}),/failed schedule or score validation/);
}
const params=parseCSV(files['06_PARAMETERS.csv']);
params.rows.find(r=>r.key==='horizon_weeks').value='1';
files['06_PARAMETERS.csv']=csv(params.rows,params.headers);
const only=await solve(files,'A',{python,timeLimitSeconds:3});
const exhausted=await solve(files,'A',{python,timeLimitSeconds:3,seed:only.schedule,
  alternativeOnly:true,alternativeCount:3,alternativeSeconds:3});
assert.equal(exhausted.status,'INFEASIBLE');
assert.equal(exhausted.feasible,false);
await assert.rejects(solve(files,'A',{python,alternativeOnly:true,alternativeCount:3,
  seed:[{...only.schedule[0],week:0}]}),/Invalid starting schedule/);
console.log('Trackspace diagnostics, closure exceptions and all three alternative searches passed');
