import {loadInstance, weeklyConflict} from './engine.js';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

// Requested dates mean consecutive standard accesses from each release week.
// This is the unoptimised input programme: ECLO and purchased capacity belong
// to the scenario search. Every required co-share implies equal group labels.
// Their connected components expose mandatory sharing chains. A joint CP-SAT
// check also tests the remaining location and contractor budgets together.
export function requestedDiagnostics(files, options={}) {
  const m = loadInstance(files), findings = [];
  const groupChecks = [], activeWeeks = new Map();
  const end = new Map(m.activities.map(a => [a.activity_id, a.release + a.work - 1]));
  const emit = (kind, week, where, parties, detail, options, severity='blocking', need=0, supply=0) => {
    findings.push({kind, week, where, parties:[...new Set(parties.map(a=>a.activity_id))].sort(),
      contracts:[...new Set(parties.map(a=>a.contract_number))].sort(), detail, options, severity, need, supply});
  };
  for (const a of m.activities) {
    if (end.get(a.activity_id) > m.horizon)
      emit('horizon', a.release, '', [a], `${a.activity_id} needs work through week ${end.get(a.activity_id)}, beyond the ${m.horizon}-week horizon.`, ['Review the workload, start date or ECLO options']);
    const p = m.activityMap.get(a.predecessor_activity_id);
    if (p && a.release <= end.get(p.activity_id))
      emit('precedence', a.release, '', [p,a], `${a.activity_id} starts in week ${a.release}; ${p.activity_id} must finish first (requested finish: week ${end.get(p.activity_id)}).`, ['Start the successor after the predecessor finishes']);
  }
  for (let week=1; week<=m.horizon; week++) {
    const active=m.activities.filter(a=>a.release<=week && end.get(a.activity_id)>=week);
    activeWeeks.set(week,active);
    const share=[], limits=[];
    const parent=active.map((_,i)=>i);
    const root=i=>parent[i]===i?i:(parent[i]=root(parent[i]));
    const union=(i,j)=>{parent[root(i)]=root(j);};
    for (let i=0;i<active.length;i++) for(let j=i+1;j<active.length;j++) {
      const a=active[i], b=active[j];
      if (weeklyConflict(a,b,true)) {
        const overlap=a.exclusion.filter(loc=>b.exclusion.includes(loc));
        const where=overlap.find(loc=>a.workLocations.includes(loc)||b.workLocations.includes(loc)) || overlap[0] || '';
        emit('buffer',week,where,[a,b],`${a.activity_id} and ${b.activity_id} have incompatible weekly closures, even in the same possession.`,['Move one activity to a different week']);
      } else if (weeklyConflict(a,b,false)) { union(i,j); share.push([i,j]); }
    }
    const groups=new Map();
    active.forEach((a,i)=>{const r=root(i);if(!groups.has(r))groups.set(r,[]);groups.get(r).push(a);});
    const cells=new Map();
    active.forEach((a,i)=>a.workLocations.forEach(loc=>{
      if(!cells.has(loc))cells.set(loc,new Map());
      const gs=cells.get(loc),r=root(i);if(!gs.has(r))gs.set(r,[]);gs.get(r).push(a);
    }));
    for (const [loc,gs] of cells) {
      const parties=[...gs.values()].flat(), cap=m.locationMap.get(loc).capacity;
      limits.push({members:parties.map(a=>active.indexOf(a)),cap,fronts:4});
      for (const members of gs.values()) {
        const types=members.map(a=>a.project.access_type);
        if(members.length>4 || (types.includes('PM') && members.length>1) || types.filter(t=>t==='PC').length>1)
          emit('mix',week,loc,members,`${members.length} teams are forced into one possession at ${loc}, exceeding the legal sharing limits.`,['Move one or more activities to another week']);
      }
      if(gs.size>cap)
        emit('capacity',week,loc,parties,`${gs.size} separate possessions are needed at ${loc}; nominal supply is ${cap}.`,['Move work or consider scenario capacity options'],'blocking',gs.size,cap);
      if([...gs.values()].some(as=>as.length>1))
        emit('contention',week,loc,parties,`Teams at ${loc} must share access in week ${week}. Other findings may still require this work to move.`,['Coordinate a legal shared possession'],'coordination',gs.size,cap);
    }
    for(const p of m.projects) {
      const buckets=[...groups.values()].map(as=>as.filter(a=>a.contract_number===p.contract_number && a.activity_type===p.activity_type)).filter(as=>as.length);
      const members=buckets.flat();
      if(members.length) limits.push({members:members.map(a=>active.indexOf(a)),cap:p.cap,fronts:p.fronts});
      if(members.length>p.cap*p.fronts)
        emit('weekly_limit',week,'',members,`${p.contract_number}/${p.activity_type} requests ${members.length} jobs; ${p.cap} accesses with ${p.fronts} workfronts can handle at most ${p.cap*p.fronts}.`,['Move activities to another week']);
      for(const as of buckets) if(as.length>p.fronts)
        emit('workfronts',week,'',as,`${p.contract_number}/${p.activity_type} needs ${as.length} simultaneous workfronts in one possession; limit is ${p.fronts}.`,['Move activities to another week']);
    }
    // Direct failures already prove this week cannot fit. Otherwise verify
    // all location and contractor budgets together, including merging groups
    // for disjoint worksites of the same contractor.
    if(!findings.some(f=>f.week===week && f.severity==='blocking' && !['precedence','horizon'].includes(f.kind)))
      groupChecks.push({week,activities:active.map(a=>a.activity_id),share,limits});
  }
  if(groupChecks.length) {
    const checked=spawnSync(options.python || process.env.CPSAT_PYTHON || 'python',
      [fileURLToPath(new URL('./check-request-groups.py',import.meta.url))],
      {input:JSON.stringify(groupChecks),encoding:'utf8',timeout:120000,maxBuffer:8*1024*1024});
    if(checked.error || checked.status!==0) throw Error(checked.error?.message || checked.stderr || 'Weekly request validation failed');
    for(const week of JSON.parse(checked.stdout))
      emit('weekly_limit',week,'',activeWeeks.get(week),`Week ${week} cannot satisfy all shared-possession, workfront and weekly-access limits together.`,['Move one or more activities to another week']);
  }
  return {type:'conflicts',conflicts:findings.sort((a,b)=>a.week-b.week||a.where.localeCompare(b.where)||a.kind.localeCompare(b.kind))};
}
