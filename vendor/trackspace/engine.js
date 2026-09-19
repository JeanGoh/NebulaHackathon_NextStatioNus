export const FILES = ['01_LINES.csv','02_STATIONS.csv','03_SECTORS.csv','04_LOCATION_SUPPLY.csv','05_BUFFER_LOCATION.csv','06_PARAMETERS.csv','07_PROJECT_DETAILS.csv','08_ACTIVITY_DETAILS.csv'];
const REQUIRED = [
 ['line_code','line_name'], ['station_id','line_code','seq','is_interchange'],
 ['sector_id','line_code','from_station_id','to_station_id','seq','is_shared'],
 ['location_id','location_kind','line_code','bound','supply_capacity'],
 ['nature_of_works','up_to_buffer_sectors','opposite_bound_required'], ['key','value'],
 ['contract_number','activity_type','nature_of_activity','contract_priority','planned_completion_date','contract_completion_date','number_of_workfronts','access_type','number_of_maximum_access_per_week'],
 ['activity_id','contract_number','activity_type','start_location_id','end_location_id','total_accesses','planned_start_date','predecessor_activity_id','activity_priority']
];
const DAY = 86400000;
export function parseCSV(text) {
 text = text.replace(/^\uFEFF/, '');
 const matrix=[]; let row=[], field='', quoted=false;
 for(let i=0;i<text.length;i++) { const c=text[i];
  if(c==='"') { if(quoted && text[i+1]==='"'){field+='"';i++;} else if(quoted || field==='') quoted=!quoted; else throw Error('Unexpected quote in CSV'); }
  else if(c===',' && !quoted){row.push(field);field='';}
  else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(x=>x!==''))matrix.push(row);row=[];field='';}
  else field+=c;
 }
 if(quoted)throw Error('Unclosed quoted CSV field');
 if(field || row.length){row.push(field);matrix.push(row);}
 if(!matrix.length)throw Error('Empty CSV');
 const headers=matrix.shift().map(x=>x.trim());
 if(new Set(headers).size!==headers.length)throw Error('Duplicate CSV column');
 return {headers,rows:matrix.map((r,i)=>{if(r.length!==headers.length)throw Error(`Row ${i+2}: expected ${headers.length} fields, got ${r.length}`);return Object.fromEntries(headers.map((h,j)=>[h,r[j].trim()]));})};
}
export function csv(rows,headers){return headers.join(',')+'\r\n'+rows.map(r=>headers.map(h=>{const v=String(r[h]??'');return /[",\r\n]/.test(v)?'"'+v.replaceAll('"','""')+'"':v;}).join(',')).join('\r\n')+'\r\n';}
function date(s){const t=Date.parse(s+'T00:00:00Z');if(!/^\d{4}-\d{2}-\d{2}$/.test(s)||!Number.isFinite(t)||new Date(t).toISOString().slice(0,10)!==s)throw Error(`Invalid date: ${s}`);return t;}
function num(v,label,min=0){const n=Number(v);if(v===''||!Number.isInteger(n)||n<min)throw Error(`${label} must be an integer ≥ ${min}`);return n;}
function unique(rows,key,label){const m=new Map();for(const r of rows){const k=key(r);if(!k||m.has(k))throw Error(`Missing or duplicate ${label}: ${k}`);m.set(k,r);}return m;}
export function loadInstance(files){
 const tables=FILES.map((f,i)=>{if(typeof files[f]!=='string')throw Error(`Missing ${f}`);const p=parseCSV(files[f]);for(const h of REQUIRED[i])if(!p.headers.includes(h))throw Error(`${f}: missing column ${h}`);if(!p.rows.length)throw Error(`${f} has no rows`);return p.rows;});
 const [lines,stations,sectors,locations,buffers,parameters,projects,activities]=tables;
 const lineMap=unique(lines,r=>r.line_code,'line');const locationMap=unique(locations,r=>r.location_id,'location');
 const projectMap=unique(projects,r=>r.contract_number+'|'+r.activity_type,'contract/type');
 const activityMap=unique(activities,r=>r.activity_id,'activity'); const params=Object.fromEntries(unique(parameters,r=>r.key,'parameter'));
 const start=date(params.horizon_start?.value||'');const horizon=num(params.horizon_weeks?.value,'horizon_weeks',1);
 if(horizon>520||activities.length>2000)throw Error('This browser edition supports up to 520 weeks and 2,000 activities.');
 const bufferMap=unique(buffers,r=>r.nature_of_works,'buffer rule');
 for(const b of buffers){b.size=num(b.up_to_buffer_sectors,'buffer sectors');if(!['0','1'].includes(b.opposite_bound_required))throw Error('opposite_bound_required must be 0 or 1');}
 const topology={};
 for(const line of lines){const ss=stations.filter(s=>s.line_code===line.line_code).sort((a,b)=>Number(a.seq)-Number(b.seq));unique(ss,r=>r.station_id,'station on line');unique(ss,r=>r.seq,'station sequence');if(ss.length<2)throw Error(`Line ${line.line_code} needs at least two stations`);for(const s of ss){num(s.seq,'station seq',1);if(!['0','1'].includes(s.is_interchange))throw Error('Invalid interchange flag');}
  const edges=[];for(let j=0;j<ss.length-1;j++){const e=sectors.filter(e=>e.line_code===line.line_code&&e.from_station_id===ss[j].station_id&&e.to_station_id===ss[j+1].station_id);if(e.length!==1)throw Error(`Missing/duplicate sector between ${ss[j].station_id} and ${ss[j+1].station_id}`);edges.push(e[0]);}
  topology[line.line_code]={stations:ss,sectors:edges};
 }
 unique(sectors,r=>r.sector_id,'sector');
 if(Object.values(topology).reduce((n,t)=>n+t.sectors.length,0)!==sectors.length)throw Error('Only linear networks are supported; extra or disconnected sectors found');
 for(const s of [...stations,...sectors])if(!lineMap.has(s.line_code))throw Error(`Unknown line ${s.line_code}`);
 for(const l of locations){l.capacity=num(l.supply_capacity,`${l.location_id} capacity`);const parts=l.location_id.split(':');if(!lineMap.has(l.line_code)||!['EB','WB'].includes(l.bound)||parts[1]!==l.line_code||parts[3]!==l.bound)throw Error(`Invalid location ${l.location_id}`);}
 for(const [line,t] of Object.entries(topology))for(const bound of ['EB','WB'])for(const id of [...t.stations.map(s=>`PLAT:${line}:${s.station_id}:${bound}`),...t.sectors.map(s=>`${s.sector_id}:${bound}`)])if(!locationMap.has(id))throw Error(`Missing location supply for ${id}`);
 for(const p of projects){p.cap=num(p.number_of_maximum_access_per_week,'weekly allocation',1);p.fronts=num(p.number_of_workfronts,'workfronts',1);p.priority=num(p.contract_priority,'contract priority',1);if(p.priority>3||!['PC','PM','C'].includes(p.access_type)||!bufferMap.has(p.nature_of_activity))throw Error(`Invalid contract attributes: ${p.contract_number}`);p.deadline=date(p.planned_completion_date);date(p.contract_completion_date);}
 const instance={lines,stations,sectors,locations,projects,activities,locationMap,projectMap,activityMap,topology,bufferMap,start,horizon};
 for(const a of activities){a.project=projectMap.get(a.contract_number+'|'+a.activity_type);if(!a.project)throw Error(`Unknown contract/type: ${a.activity_id}`);a.work=num(a.total_accesses,'total_accesses',1);a.priority=num(a.activity_priority,'activity priority',1);if(a.priority>3)throw Error('Activity priority must be 1, 2 or 3');a.release=Math.max(1,Math.floor((date(a.planned_start_date)-start)/(7*DAY))+1);a.due=Math.floor((a.project.deadline-start+DAY)/(7*DAY));if(a.release>1040||a.work>1040)throw Error(`${a.activity_id}: planning range exceeds browser limits`);Object.assign(a,footprint(instance,a));}
 const visiting=new Set(),done=new Set();function visit(a){if(visiting.has(a.activity_id))throw Error(`Dependency cycle at ${a.activity_id}`);if(done.has(a.activity_id))return;visiting.add(a.activity_id);if(a.predecessor_activity_id){const p=activityMap.get(a.predecessor_activity_id);if(!p)throw Error(`Unknown predecessor ${a.predecessor_activity_id}`);visit(p);}visiting.delete(a.activity_id);done.add(a.activity_id);}activities.forEach(visit);
 return instance;
}
export function footprint(m,a){
 const first=m.locationMap.get(a.start_location_id), last=m.locationMap.get(a.end_location_id);if(!first||!last||first.line_code!==last.line_code||first.bound!==last.bound)throw Error(`${a.activity_id}: endpoints must exist on the same line and bound`);
 const line=first.line_code,bound=first.bound,t=m.topology[line];
 function span(id){const p=t.stations.findIndex(s=>id===`PLAT:${line}:${s.station_id}:${bound}`);if(p>=0)return [p,p];const e=t.sectors.findIndex(s=>id===`${s.sector_id}:${bound}`);if(e<0)throw Error(`Invalid endpoint ${id}`);return [e,e+1];}
 const r1=span(a.start_location_id),r2=span(a.end_location_id),lo=Math.min(...r1,...r2),hi=Math.max(...r1,...r2);
 function range(l,b,low,high){const x=m.topology[l];return [...x.stations.slice(low,high+1).map(s=>`PLAT:${l}:${s.station_id}:${b}`),...x.sectors.slice(low,high).map(s=>`${s.sector_id}:${b}`)];}
 const rule=m.bufferMap.get(a.project.nature_of_activity),workLocations=range(line,bound,lo,hi), low=Math.max(0,lo-rule.size), high=Math.min(t.stations.length-1,hi+rule.size);
 const exclusion=new Set(range(line,bound,low,high));const affectedLines=new Set([line]);
 if(rule.opposite_bound_required==='1')range(line,bound==='EB'?'WB':'EB',low,high).forEach(x=>exclusion.add(x));
 if(a.project.nature_of_activity==='Live') {
  const hubs=t.stations.slice(low,high+1).filter(s=>s.is_interchange==='1').map(s=>s.station_id);
  for(const [other,x] of Object.entries(m.topology))if(other!==line){const common=x.stations.filter(s=>s.is_interchange==='1'&&hubs.includes(s.station_id));if(common.length){affectedLines.add(other);const indices=x.stations.map((s,i)=>s.is_interchange==='1'?i:-1).filter(i=>i>=0),otherLow=Math.max(0,Math.min(...indices)-rule.size),otherHigh=Math.min(x.stations.length-1,Math.max(...indices)+rule.size);for(const b of ['EB','WB'])range(other,b,otherLow,otherHigh).forEach(id=>exclusion.add(id));}}
 }
 return {line,bound,workLocations,exclusion:[...exclusion],affectedLines:[...affectedLines],signature:[...workLocations].sort().join('|')};
}
function intersects(a,b){return a.some(x=>b.includes(x));}
function legalMix(as){return as.length<=4&&(as.some(a=>a.project.access_type==='PM')?as.length===1:as.filter(a=>a.project.access_type==='PC').length<=1);}
// Called only for activities assigned to the same possession window: exports
// give them the same group at every common work location. Rule 5 exempts direct
// co-sharers from each other's closures. This exemption is NOT transitive.
export function canCoShare(a,b){return legalMix([a,b])&&intersects(a.workLocations,b.workLocations);}
export function conflicts(a,b){if(canCoShare(a,b))return false;return intersects(a.exclusion,b.exclusion);}
// Different group labels do not establish physical separation to the external
// validator. Only direct, legal co-sharing in the SAME group gets an exemption.
// A platform-only buffer overlap with neither job working in the other's full
// closure is the supplied Trackspace platform-buffer exception.
export function weeklyConflict(a,b,sameGroup){const overlap=a.exclusion.filter(loc=>b.exclusion.includes(loc));
 if(overlap.length&&overlap.every(loc=>loc.startsWith('PLAT:'))&&!intersects(a.workLocations,b.exclusion)&&!intersects(b.workLocations,a.exclusion))return false;
 return !(sameGroup&&canCoShare(a,b))&&overlap.length>0;}
export function weekDate(m,w){return new Date(m.start+(w*7-1)*DAY).toISOString().slice(0,10);}
const tier={1:100,2:10,3:1},nudge={1:0.3,2:0.2,3:0};
export function validate(m,schedule,scenario){
 const errors=[];const err=(rule,detail)=>{if(errors.length<300)errors.push({rule,detail,severity:'hard'});};
 const byActivity=new Map(),byWeek=new Map();
 for(const r of schedule){const a=m.activityMap.get(r.activity_id);if(!a){err('schema',`Unknown activity ${r.activity_id}`);continue;}if(!Number.isInteger(r.week)||r.week<1||!Number.isInteger(r.night)||r.night<1||!Number.isInteger(r.access_night)||r.access_night<1||![0,1].includes(r.eclo)){err('schema',`Invalid access for ${r.activity_id}`);continue;}
  if(scenario==='C'&&r.week>m.horizon){err('horizon',`${a.activity_id}: week ${r.week} outside 1..${m.horizon}`);continue;}
  if(r.week<a.release)err('planned_start',`${a.activity_id}: week ${r.week} precedes release week ${a.release}`);
  if(scenario==='A'&&r.eclo)err('eclo',`${a.activity_id}: ECLO forbidden in A`);
  if(!byActivity.has(a.activity_id))byActivity.set(a.activity_id,[]);byActivity.get(a.activity_id).push(r);
  if(!byWeek.has(r.week))byWeek.set(r.week,[]);byWeek.get(r.week).push({...r,a});
 }
 let weighted=0;const activityResults=[];
 for(const a of m.activities){const rs=byActivity.get(a.activity_id)||[];const units=rs.reduce((v,r)=>v+(r.eclo?1.5:1),0);if(units<a.work)err('workload',`${a.activity_id}: ${units}/${a.work} work units scheduled`);if(new Set(rs.map(r=>r.week)).size!==rs.length)err('weekly_activity',`${a.activity_id}: more than one access in a week`);
  if(rs.map(r=>r.access_seq).sort((a,b)=>a-b).some((x,i)=>x!==i+1))err('sequence',`${a.activity_id}: access sequences must start at 1 and be contiguous`);
  const end=rs.length?Math.max(...rs.map(r=>r.week)):null;const overrun=end?Math.max(0,Math.round((date(weekDate(m,end))-a.project.deadline)/DAY)):0;
  if(scenario==='B'&&overrun)err('planned_date',`${a.activity_id}: ${overrun} days beyond planned completion`);
  if(a.predecessor_activity_id&&rs.length){const pred=byActivity.get(a.predecessor_activity_id)||[];const predWork=pred.reduce((s,r)=>s+(r.eclo?1.5:1),0);if(predWork<m.activityMap.get(a.predecessor_activity_id).work||!pred.length||Math.min(...rs.map(r=>r.week))<=Math.max(...pred.map(r=>r.week)))err('predecessor',`${a.activity_id}: predecessor must finish in an earlier week`);}
  activityResults.push({activity_id:a.activity_id,units,required:a.work,completion_week:end,overrun_days:overrun});
 }
 let excess=0;const utilization=[];
 for(const [week,rs] of byWeek){const locations=new Map(),contracts=new Map();
  for(const r of rs){for(const loc of r.a.workLocations){if(!locations.has(loc))locations.set(loc,new Map());const nights=locations.get(loc);if(!nights.has(r.night))nights.set(r.night,[]);nights.get(r.night).push(r.a);}
   const key=r.a.contract_number+'|'+r.a.activity_type;if(!contracts.has(key))contracts.set(key,[]);contracts.get(key).push(r);
  }
  for(const [loc,nights] of locations){const cap=m.locationMap.get(loc).capacity, extra=Math.max(0,nights.size-cap);excess+=extra;utilization.push({week,location_id:loc,used:nights.size,capacity:cap,excess:extra});if((scenario==='A'&&extra)||(scenario==='C'&&extra>1))err('capacity',`${loc}, week ${week}: ${nights.size} possessions / ${cap} nominal`);for(const [night,as] of nights)if(!legalMix(as))err('mix',`${loc}, week ${week}, possession ${night}: illegal access mix`);}
  for(const [key,as] of contracts){const p=as[0].a.project;const local=new Set(as.map(r=>r.access_night));if(local.size>p.cap||as.some(r=>r.access_night>p.cap))err('allocation',`${key}, week ${week}: weekly access budget exceeded`);for(const n of local){const subset=as.filter(r=>r.access_night===n);if(subset.length>p.fronts)err('workfronts',`${key}, week ${week}, index ${n}: too many teams`);if(new Set(subset.map(r=>r.night)).size>1)err('night_mapping',`${key}: one local access index maps to different possessions`);}for(const n of new Set(as.map(r=>r.night)))if(new Set(as.filter(r=>r.night===n).map(r=>r.access_night)).size>1)err('night_mapping',`${key}: simultaneous work uses different local indices`);}
  for(let i=0;i<rs.length;i++)for(let j=i+1;j<rs.length;j++)if(weeklyConflict(rs[i].a,rs[j].a,rs[i].night===rs[j].night))err('closure',`Week ${week}, groups ${rs[i].night}/${rs[j].night}: ${rs[i].activity_id} conflicts with ${rs[j].activity_id}`);
 }
 const ecloWindows={};for(const line of m.lines){const weeks=schedule.filter(r=>r.eclo&&m.activityMap.get(r.activity_id)?.affectedLines.includes(line.line_code)).map(r=>r.week);if(weeks.length){const lo=Math.min(...weeks),hi=Math.max(...weeks);ecloWindows[line.line_code]=[lo,hi];if(scenario==='C'&&hi-lo>1)err('eclo_window',`${line.line_code}: ECLO spans weeks ${lo}–${hi}`);}}
 const results=[...new Set(m.projects.map(p=>p.contract_number))].map(id=>{const acts=m.activities.filter(a=>a.contract_number===id), ar=activityResults.filter(r=>acts.some(a=>a.activity_id===r.activity_id));const complete=ar.length>0&&ar.every(r=>r.units>=r.required);const end=complete?Math.max(...ar.map(r=>r.completion_week)):null;const deadline=Math.min(...m.projects.filter(p=>p.contract_number===id).map(p=>p.deadline));return {scenario,contract_number:id,simulated_completion_date:end?weekDate(m,end):'',overrun_days:end?Math.max(0,Math.round((date(weekDate(m,end))-deadline)/DAY)):null};});
 const contractOverrun=new Map(results.map(r=>[r.contract_number,r.overrun_days||0]));
 weighted=m.activities.reduce((sum,a)=>sum+tier[a.project.priority]*(1+nudge[a.priority])*contractOverrun.get(a.contract_number),0);
 const eclo=schedule.filter(r=>r.eclo).length,score=(scenario==='B'?0:weighted)+(scenario==='A'?0:7*excess+5*eclo);
 return {feasible:errors.length===0,hard_violations:errors,score:errors.length?null:Math.round(score*10)/10,priority_weighted_score:Math.round(weighted*10)/10,excess_access_nights_total:excess,eclo_nights_total:eclo,overrun_days_total:results.reduce((s,r)=>s+(r.overrun_days||0),0),contracts_overrunning:results.filter(r=>r.overrun_days>0).length,completed_activities:activityResults.filter(r=>r.units>=r.required).length,activityResults,results,utilization,ecloWindows};
}
export function attempt(m,scenario,seed,windows,allowEclo,explore=false,earlyEclo=false){
 let state=(seed+1)>>>0;const random=()=>{state=(Math.imul(1664525,state)+1013904223)>>>0;return state/4294967296;};
 const weights=explore?new Map(m.activities.map(a=>[a.activity_id,random()])):null;
 const mode=seed%8;
 const remaining=new Map(m.activities.map(a=>[a.activity_id,a.work])),done=new Map(),schedule=[],reasons=new Map();
 const horizon=scenario==='C'?m.horizon:Math.min(1040,Math.max(m.horizon+52,...m.activities.map(a=>a.release+a.work+52)));
 for(let week=1;week<=horizon && remaining.size;week++){
  const placed=[], local=new Map();
  const ready=m.activities.filter(a=>remaining.has(a.activity_id)&&week>=a.release&&(!a.predecessor_activity_id||(done.has(a.predecessor_activity_id)&&done.get(a.predecessor_activity_id)<week)));
  const hash=a=>((Number(a.activity_id.replace(/\D/g,''))||a.activity_id.length)*1664525+seed*1013904223)>>>0;
  ready.sort((a,b)=>{const slackA=a.due-week-Math.ceil(remaining.get(a.activity_id)),slackB=b.due-week-Math.ceil(remaining.get(b.activity_id));if(explore){const value=(x,slack)=>{const noise=weights.get(x.activity_id)*(mode<4?12:35);if(mode===0)return slack+noise;if(mode===1)return x.due+noise;if(mode===2)return x.project.priority*15+slack+noise;if(mode===3)return -remaining.get(x.activity_id)+noise;if(mode===4)return x.project.priority*10+noise;if(mode===5)return noise;if(mode===6)return slack*2+x.project.priority*10+noise;return x.due-remaining.get(x.activity_id)*2+noise;};return value(a,slackA)-value(b,slackB)||hash(a)-hash(b);}if(seed%3===0)return a.project.priority-b.project.priority||slackA-slackB||a.priority-b.priority||hash(a)-hash(b);if(seed%3===1)return slackA-slackB||a.project.priority-b.project.priority||hash(a)-hash(b);return a.due-b.due||a.project.priority-b.project.priority||hash(a)-hash(b);});
  for(const a of ready){const key=a.contract_number+'|'+a.activity_type,p=a.project,left=remaining.get(a.activity_id);if(!local.has(key))local.set(key,new Map());const mapping=local.get(key);
   const ecloLegal=scenario!=='A'&&allowEclo&&a.affectedLines.every(l=>scenario==='B'||(week>=windows[l]&&week<=windows[l]+1));
   const need=left>Math.max(0,a.due-week+1);const eclo=ecloLegal&&left>1&&(earlyEclo||need||(seed>=6&&week+Math.ceil(left)-1>=a.due))?1:0;
   let best=null;const blocked=new Set();const maxNight=Math.max(0,...placed.map(r=>r.night))+1;
   for(let night=1;night<=maxNight;night++){
    const same=placed.filter(r=>r.night===night);if((!mapping.has(night)&&mapping.size>=p.cap)||same.filter(r=>r.a.contract_number===a.contract_number&&r.a.activity_type===a.activity_type).length>=p.fronts){blocked.add('Weekly access / workfront budget');continue;}
    const collision=placed.find(r=>weeklyConflict(a,r.a,r.night===night));
    if(collision){blocked.add(`Weekly closure separation from ${collision.a.activity_id}`);continue;}
    let extra=0,valid=true;for(const loc of a.workLocations){const existing=new Set(placed.filter(r=>r.a.workLocations.includes(loc)).map(r=>r.night));const used=existing.size+(existing.has(night)?0:1),cap=m.locationMap.get(loc).capacity;
     if(!legalMix([...same.filter(r=>r.a.workLocations.includes(loc)).map(r=>r.a),a])){blocked.add('Possession sharing limit');valid=false;break;}
     if((scenario==='A'&&used>cap)||(scenario==='C'&&used>cap+1)){blocked.add(`Capacity at ${loc}`);valid=false;break;}extra+=Math.max(0,used-cap)-Math.max(0,existing.size-cap);
    }
    if(valid){const cost=extra*7+night*0.0001;if(!best||cost<best.cost)best={night,cost,extra};}
   }
   if(best&&scenario==='C'&&best.extra&&seed%2===0){const futureDelay=Math.max(0,week+Math.ceil(left)-a.due)*7*tier[p.priority]*(1+nudge[a.priority]);if(best.extra*7>futureDelay){blocked.add('Deferred to avoid additional access cost');best=null;}}
   if(!best){if(!reasons.has(a.activity_id))reasons.set(a.activity_id,[]);if(reasons.get(a.activity_id).length<8)reasons.get(a.activity_id).push({week,reasons:[...blocked].slice(0,3)});continue;}
   if(!mapping.has(best.night))mapping.set(best.night,mapping.size+1);
   const r={activity_id:a.activity_id,week,night:best.night,access_night:mapping.get(best.night),eclo};placed.push({...r,a});schedule.push(r);
   const rest=left-(eclo?1.5:1);if(rest<=0){remaining.delete(a.activity_id);done.set(a.activity_id,week);}else remaining.set(a.activity_id,rest);
  }
 }
 const seq=new Map();schedule.sort((a,b)=>a.activity_id.localeCompare(b.activity_id)||a.week-b.week).forEach(r=>{seq.set(r.activity_id,(seq.get(r.activity_id)||0)+1);r.access_seq=seq.get(r.activity_id);});
 return {schedule,reasons:Object.fromEntries(reasons)};
}
export function solve(m,scenario,progress=()=>{}){
 if(!['A','B','C'].includes(scenario))throw Error('Unknown scenario');let best=null;
 const candidates=[{}];
 if(scenario==='C'){
  const candidatesByLine=m.lines.map(l=>{const counts=new Map();for(const a of m.activities.filter(a=>a.affectedLines.includes(l.line_code))){const w=Math.max(a.release,a.due-1);counts.set(w,(counts.get(w)||0)+a.work*tier[a.project.priority]);}return [l.line_code,[...counts].sort((a,b)=>b[1]-a[1]).slice(0,4).map(x=>x[0])];});
  for(let j=0;j<4;j++)candidates.push(Object.fromEntries(candidatesByLine.map(([l,ws])=>[l,ws[j%ws.length]||1])));
 }
 const rounds=scenario==='A'?9:scenario==='B'?12:20;
 for(let i=0;i<rounds;i++){const windows=candidates[i%candidates.length];const result=attempt(m,scenario,i,windows,scenario==='B'?i!==0:scenario==='C'&&i%candidates.length!==0);const report=validate(m,result.schedule,scenario);const rank=(report.feasible?0:1e10)+(m.activities.length-report.completed_activities)*1e8+report.hard_violations.length*1e6+(report.score??report.priority_weighted_score+7*report.excess_access_nights_total+5*report.eclo_nights_total);
  if(!best||rank<best.rank)best={...result,report,rank,scenario};progress({scenario,iteration:i+1,total:rounds,feasible:best.report.feasible,score:best.report.score});if(best.report.feasible&&best.report.score===0)break;
 }
 delete best.rank;return best;
}
export function exportFiles(m,result){const occupancy=[];for(const r of result.schedule)for(const location_id of m.activityMap.get(r.activity_id).workLocations)occupancy.push({activity_id:r.activity_id,week:r.week,location_id,co_share_group:`w${r.week}n${r.night}`});return {
 'SCHEDULE_ACCESS.csv':csv(result.schedule,['activity_id','access_seq','week','eclo','access_night']),
 'SCHEDULE_OCCUPANCY.csv':csv(occupancy,['activity_id','week','location_id','co_share_group']),
 'RESULTS.csv':csv(result.report.results,['scenario','contract_number','simulated_completion_date','overrun_days'])
 };}
