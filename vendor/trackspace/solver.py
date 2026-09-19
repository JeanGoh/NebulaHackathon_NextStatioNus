import sys,json
from ortools.sat.python import cp_model

D={}; acts=[]; H=0

def run(s):
 m=cp_model.CpModel(); x={}; e={}; y={}; g={}; ends={}; starts={}
 baseline={(r['activity_id'],r['week']):r for r in D['schedules'][s]}
 K=max(D.get('slot_limit',8),max((r['night'] for r in D['schedules'][s]),default=0))
 for a in acts:
  aid=a['activity_id']; weeks=range(max(1,a['release']),min(H,a['due'] if s=='B' else H)+1)
  for w in weeks:
   key=(aid,w); x[key]=m.new_bool_var(f'x{aid}_{w}'); e[key]=m.new_bool_var(f'e{aid}_{w}'); m.add(e[key]<=x[key])
   if s=='A':m.add(e[key]==0)
   g[key]=m.new_int_var(0,K,f'g{aid}_{w}')
   yy=[]
   for k in range(1,K+1):
    v=m.new_bool_var(f'y{aid}_{w}_{k}'); y[aid,w,k]=v; yy.append(v)
    m.add_hint(v,int(key in baseline and baseline[key]['night']==k))
   m.add(sum(yy)==x[key]);m.add(g[key]==sum((k+1)*v for k,v in enumerate(yy)))
   m.add_hint(x[key],int(key in baseline));m.add_hint(e[key],baseline.get(key,{}).get('eclo',0));m.add_hint(g[key],baseline.get(key,{}).get('night',0))
  keys=[key for key in x if key[0]==aid]
  if not keys:
   return {'scenario':s,'status':'INFEASIBLE','horizon':H,'slot_limit':K}
  m.add(sum(2*x[key]+e[key] for key in keys)>=2*a['work'])
  ends[aid]=m.new_int_var(1,H,'end'+aid);m.add_max_equality(ends[aid],[w*x[aid,w] for _,w in keys])
  starts[aid]=m.new_int_var(1,H,'start'+aid);m.add_min_equality(starts[aid],[w+(H+1)*(1-x[aid,w]) for _,w in keys])
 for a in acts:
  if a['predecessor_activity_id']:m.add(starts[a['activity_id']]>ends[a['predecessor_activity_id']])
 for i,a in enumerate(acts):
  for b in acts[i+1:]:
   overlap=set(a['exclusion'])&set(b['exclusion'])
   if not overlap:continue
   if all(loc.startswith('PLAT:') for loc in overlap) and not (set(a['workLocations'])&set(b['exclusion']) or set(b['workLocations'])&set(a['exclusion'])):continue
   types=[a['project']['access_type'],b['project']['access_type']]
   share=bool(set(a['workLocations'])&set(b['workLocations'])) and 'PM' not in types and types.count('PC')<=1
   for w in range(1,H+1):
    ka=(a['activity_id'],w);kb=(b['activity_id'],w)
    if ka not in x or kb not in x:continue
    if share:m.add(g[ka]==g[kb]).only_enforce_if([x[ka],x[kb]])
    else:m.add(x[ka]+x[kb]<=1)
 extras=[]
 for loc in D['locations']:
  aa=[a for a in acts if loc['location_id'] in a['workLocations']]
  if not aa:continue
  for w in range(1,H+1):
   qs=[]
   for k in range(1,K+1):
    vs=[y[a['activity_id'],w,k] for a in aa if (a['activity_id'],w) in x]
    if not vs:continue
    q=m.new_bool_var('loc');m.add_max_equality(q,vs);qs.append(q);m.add(sum(vs)<=4)
   cap=int(loc['capacity'])
   if s=='A':m.add(sum(qs)<=cap)
   else:
    extra=m.new_int_var(0,K,'extra');m.add_max_equality(extra,[0,sum(qs)-cap]);extras.append(extra)
    if s=='C':m.add(extra<=1)
 for p in D['projects']:
  aa=[a for a in acts if a['contract_number']==p['contract_number'] and a['activity_type']==p['activity_type']]
  for w in range(1,H+1):
   zs=[]
   for k in range(1,K+1):
    vs=[y[a['activity_id'],w,k] for a in aa if (a['activity_id'],w) in x]
    if not vs:continue
    z=m.new_bool_var('contractslot');m.add_max_equality(z,vs);zs.append(z);m.add(sum(vs)<=p['fronts'])
   m.add(sum(zs)<=p['cap'])
 if s=='C':
  for line in set(l for a in acts for l in a['affectedLines']):
   start=m.new_int_var(1,H,'eclostart'+line)
   for a in acts:
    if line not in a['affectedLines']:continue
    for w in range(1,H+1):
     if (a['activity_id'],w) in e:
      v=e[a['activity_id'],w];m.add(start<=w).only_enforce_if(v);m.add(start>=w-1).only_enforce_if(v)
 delays=[]
 for contract in set(a['contract_number'] for a in acts):
  aa=[a for a in acts if a['contract_number']==contract]
  end=m.new_int_var(1,H,'contractend');m.add_max_equality(end,[ends[a['activity_id']] for a in aa])
  deadline=min(a['project']['deadline'] for a in aa);offset=round((deadline-D['start'])/86400000)
  late=m.new_int_var(0,max(H*7,H*7-offset),'late');m.add_max_equality(late,[0,7*end-1-offset])
  coef=sum({1:100,2:10,3:1}[a['project']['priority']]*{1:13,2:12,3:10}[a['priority']] for a in aa)
  delays.append(coef*late)
 objective=(sum(delays) if s!='B' else 0)+(70*sum(extras)+50*sum(e.values()) if s!='A' else 0)
 scale=len(x)+1
 m.minimize(objective*scale+sum(x.values()))
 solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=D.get('time_limit_seconds',120);solver.parameters.num_search_workers=8;solver.parameters.random_seed=1
 candidates=[]
 attempts=[]
 alternative_only=D.get('alternative_only',False)
 if alternative_only:
  # Search different week/ECLO choices without rerunning or replacing the
  # already validated chosen plan. Group relabellings do not count.
  choices=[v.Not() if key in baseline else v for key,v in x.items()]
  choices += [v.Not() if baseline.get(key,{}).get('eclo',0) else v for key,v in e.items()]
  m.add_bool_or(choices)
  m.clear_hints()
  solver.parameters.max_time_in_seconds=D.get('alternative_seconds',15)
 for attempt in range(D.get('alternative_count',0) if alternative_only else 1+D.get('alternative_count',0)):
  if attempt:
   # Exclude identical activity-week/ECLO choices, irrespective of arbitrary
   # group numbers. Each additional solve uses the SAME constraints/objective.
   choices=list(x.values())+list(e.values())
   m.add_bool_or([v.Not() if solver.value(v) else v for v in choices])
   m.clear_hints()
   solver.parameters.max_time_in_seconds=D.get('alternative_seconds',15)
  status=solver.solve(m)
  label=solver.status_name(status)
  attempts.append(label)
  if status not in [cp_model.OPTIMAL,cp_model.FEASIBLE]:
   break
  result={'scenario':s,'status':label,'wall_seconds':solver.wall_time,'slot_limit':K,'horizon':H}
  result.update(score=solver.value(objective)/10,bound=(int(solver.best_objective_bound)//scale)/10,accesses=sum(solver.value(v) for v in x.values()))
  rows=[]
  for a in acts:
   aid=a['activity_id'];seq=0
   for w in range(1,H+1):
    if (aid,w) in x and solver.value(x[aid,w]):
     seq+=1;rows.append({'activity_id':aid,'access_seq':seq,'week':w,'eclo':solver.value(e[aid,w]),'night':solver.value(g[aid,w])})
  amap={a['activity_id']:a for a in acts}
  for r in rows:
   a=amap[r['activity_id']];nights=sorted(set(t['night'] for t in rows if t['week']==r['week'] and amap[t['activity_id']]['contract_number']==a['contract_number'] and amap[t['activity_id']]['activity_type']==a['activity_type']))
   r['access_night']=nights.index(r['night'])+1
  result['schedule']=rows
  candidates.append(result)
 if not candidates:
  return {'scenario':s,'status':attempts[0],'horizon':H,'slot_limit':K,'alternative_search_status':attempts if alternative_only else []}
 # A time-limited later solve can improve an earlier incumbent; always display
 # the lowest validated candidate as chosen. The initial bound remains global.
 global_bound=candidates[0]['bound']
 candidates.sort(key=lambda r:(r['score'],r['accesses']))
 result=candidates[0]
 result['bound']=global_bound
 result['status']='OPTIMAL' if abs(result['score']-global_bound)<.001 else 'FEASIBLE'
 result['alternatives']=candidates[1:]
 result['alternative_search_status']=attempts if alternative_only else attempts[1:]
 return result

def solve_payload(payload):
 global D,acts,H
 D=payload; acts=D['activities']; H=D['horizon']
 return run(D['scenario'])

if __name__=='__main__':
 print(json.dumps(solve_payload(json.load(sys.stdin))),flush=True)
