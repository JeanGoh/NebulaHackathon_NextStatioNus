import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {loadInstance,validate,exportFiles} from './engine.js';

export function prepare(files,scenario,options={}){
 if(!['A','B','C'].includes(scenario))throw Error('Scenario must be A, B or C');
 const model=loadInstance(files);
 const seconds=options.timeLimitSeconds??120,slots=options.slotLimit??8;
 const alternatives=options.alternativeCount??0,alternativeSeconds=options.alternativeSeconds??15;
 if(!Number.isInteger(alternatives)||alternatives<0||alternatives>3||!Number.isFinite(alternativeSeconds)||alternativeSeconds<1||alternativeSeconds>120)throw Error('Invalid alternative search limits');
 if(!Number.isInteger(slots)||slots<1||slots>64||!Number.isFinite(seconds)||seconds<1||seconds>600)throw Error('Invalid search limits');
 const seed=options.seed??[];
 if(seed.length&&!validate(model,seed,scenario).feasible)throw Error('Invalid starting schedule');
 const alternativeOnly=options.alternativeOnly??false;
 if(alternativeOnly&&(!seed.length||alternatives<1))throw Error('Alternative-only search requires a validated chosen schedule and a positive count');
 return {model,payload:{start:model.start,horizon:model.horizon,activities:model.activities,locations:model.locations,projects:model.projects,scenario,schedules:{[scenario]:seed},slot_limit:slots,time_limit_seconds:seconds,alternative_count:alternatives,alternative_seconds:alternativeSeconds,alternative_only:alternativeOnly}};
}

export function finish(model,cp){
 if(!cp.schedule)return {scenario:cp.scenario,status:cp.status,feasible:false,score:null,schedule:[],solver:cp,csvFiles:null,message:'No feasible solution found within these search limits; this does not prove unrestricted impossibility.'};
 const report=validate(model,cp.schedule,cp.scenario);
 if(!report.feasible||Math.abs(report.score-cp.score)>.001)throw Error('Solver output failed schedule or score validation: '+JSON.stringify(report.hard_violations));
 const result={scenario:cp.scenario,schedule:cp.schedule,report};
 const alternatives=(cp.alternatives||[]).map(candidate=>finish(model,candidate));
 return {...result,status:cp.status,feasible:true,score:report.score,solver:{status:cp.status,bound:cp.bound,horizon:cp.horizon,slot_limit:cp.slot_limit,wall_seconds:cp.wall_seconds},csvFiles:exportFiles(model,result),alternatives,alternativeSearchStatus:cp.alternative_search_status||[]};
}

// Server-side only: do not import this Node/Python bridge in browser bundles.
// Run one solve at a time per instance; cancellation kills the Python child.
export async function solve(files,scenario,options={}){
 const {model,payload}=prepare(files,scenario,options);
 const cp=await new Promise((resolve,reject)=>{
  const child=spawn(options.python??process.env.CPSAT_PYTHON??'python',[fileURLToPath(new URL('./solver.py',import.meta.url))],{windowsHide:true,signal:options.signal});
  let stdout='',stderr='';
  const timer=setTimeout(()=>{child.kill();reject(Error('Solver process timed out'));},(payload.time_limit_seconds+payload.alternative_count*payload.alternative_seconds+60)*1000);
  child.stdout.on('data',b=>stdout+=b);child.stderr.on('data',b=>stderr=(stderr+b).slice(-4000));child.stdin.on('error',()=>{});
  child.on('error',e=>{clearTimeout(timer);reject(e);});
  child.on('close',code=>{clearTimeout(timer);if(code!==0)return reject(Error(stderr||'Python solver failed'));try{resolve(JSON.parse(stdout));}catch(e){reject(e);}});
  child.stdin.end(JSON.stringify(payload));
 });
 return finish(model,cp);
}
