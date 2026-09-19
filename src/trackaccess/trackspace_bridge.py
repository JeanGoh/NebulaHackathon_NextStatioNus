"""Run the local Trackspace planner and translate its output for this UI.

Keeping this bridge deliberately small means the scenario cards in SMRT use
the exact same JavaScript engine as the Trackspace application, rather than a
similar-but-different Python reimplementation.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .conflicts import Conflict
from .submission import Access, Occupancy, Result, Submission


@dataclass
class TrackspaceOutcome:
    submission: Submission
    status: str
    objective: float
    best_bound: float
    wall_time: float
    schedule_end: int
    report: dict
    enhanced: bool = False          # True when the CP-SAT scheduler ran
    alternatives: list[dict] = field(default_factory=list)
    optimality: dict | None = None
    csv_files: dict[str, str] | None = None


_CP_SAT_RUNNER = r"""
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const [schedulerPath, enginePath, dataDir, scenario, pythonPath, seconds, alternativeCount] = process.argv.slice(1);
const engine = await import(pathToFileURL(enginePath).href);
const scheduler = await import(pathToFileURL(schedulerPath).href);
const files = Object.fromEntries(await Promise.all(engine.FILES.map(async f =>
  [f, await readFile(join(dataDir, f), 'utf8')]
)));
const model = engine.loadInstance(files);
process.stdout.write(JSON.stringify({type:'progress', info:{iteration:0,total:1,stage:'CP-SAT search'}}) + '\n');
const result = await scheduler.solve(files, scenario, {
  python: pythonPath, timeLimitSeconds: Number(seconds), slotLimit: 8,
  alternativeCount: Number(alternativeCount), alternativeSeconds: 15,
});
const occupancy = result.schedule.flatMap(r => model.activityMap.get(r.activity_id)
  .workLocations.map(location_id => ({activity_id:r.activity_id, week:r.week,
    location_id, co_share_group:`w${r.week}n${r.night}`})));
if (result.report) result.report.footprints = Object.fromEntries(model.activities.map(a =>
  [a.activity_id, {workLocations:a.workLocations, exclusion:a.exclusion}]));
process.stdout.write(JSON.stringify({type:'result', ...result, occupancy,
  schedule_end:Math.max(result.solver?.horizon || 1,
    ...result.schedule.map(r => r.week), 1)}) + '\n');
"""


_REQUEST_CONFLICT_RUNNER = r"""
import {readFile} from 'node:fs/promises';
import {join, dirname} from 'node:path';
import {pathToFileURL} from 'node:url';
const [enginePath, dataDir, pythonPath] = process.argv.slice(1);
const engine = await import(pathToFileURL(enginePath).href);
const {requestedDiagnostics} = await import(pathToFileURL(join(dirname(enginePath),'request-diagnostics.mjs')).href);
const files = Object.fromEntries(await Promise.all(engine.FILES.map(async f =>
  [f, await readFile(join(dataDir, f), 'utf8')]
)));
process.stdout.write(JSON.stringify(requestedDiagnostics(files, {python:pythonPath})) + '\n');
"""


_ALTERNATIVES_RUNNER = r"""
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const [schedulerPath, enginePath, dataDir, scenario, pythonPath, seconds, count] = process.argv.slice(1);
const engine = await import(pathToFileURL(enginePath).href);
const scheduler = await import(pathToFileURL(schedulerPath).href);
const files = Object.fromEntries(engine.FILES.map(f => [f,readFileSync(join(dataDir,f),'utf8')]));
const seed = JSON.parse(readFileSync(0,'utf8'));
const result = await scheduler.solve(files, scenario, {
  python:pythonPath, timeLimitSeconds:Number(seconds), slotLimit:8,
  alternativeCount:Number(count), alternativeSeconds:Number(seconds),
  alternativeOnly:true, seed,
});
const candidates = result.feasible ? [result,...result.alternatives] : [];
// No chosen-plan promotion: the UI's selected plan and CSVs stay unchanged.
process.stdout.write(JSON.stringify({
  candidates:candidates.map(({alternatives,alternativeSearchStatus,...candidate})=>candidate),
  statuses:result.alternativeSearchStatus || result.solver?.alternative_search_status || [result.status],
}));
"""


def search_alternatives(data_dir: str | Path, scenario: str, outcome: TrackspaceOutcome,
                        count: int = 3, seconds: float = 15) -> tuple[list[dict], list[str]]:
    """Read-only extra search; never mutate the chosen plan or its exports."""
    if not outcome.report.get('feasible') or not outcome.submission.accesses:
        raise ValueError('A validated chosen plan is required')
    if not isinstance(count, int) or not 1 <= count <= 3:
        raise ValueError('Request between 1 and 3 alternatives')
    limit = max(1.0, min(float(seconds), 120.0))
    ok, why = availability()
    if not ok:
        raise TrackspaceUnavailable(why)
    groups = {}
    for row in outcome.submission.occupancies:
        groups.setdefault((row.activity_id, row.week), set()).add(row.co_share_group)
    rows = []
    for a in outcome.submission.accesses:
        gs = groups.get((a.activity_id, a.week), set())
        match = re.fullmatch(r'w(\d+)n(\d+)', next(iter(gs))) if len(gs) == 1 else None
        if not match or int(match[1]) != a.week:
            raise ValueError('Chosen plan has inconsistent Trackspace possession groups')
        rows.append(dict(activity_id=a.activity_id, access_seq=a.access_seq, week=a.week,
                         eclo=int(a.eclo), access_night=a.access_night, night=int(match[2])))
    try:
        process = subprocess.run(
            ['node', '--input-type=module', '-e', _ALTERNATIVES_RUNNER,
             str(SCHEDULER), str(_engine_path()), str(Path(data_dir)), scenario.upper(),
             sys.executable, str(limit), str(count)], input=json.dumps(rows),
            capture_output=True, text=True, timeout=count*limit+70)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Alternative search timed out; the chosen plan is unchanged') from exc
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or 'Alternative search failed; the chosen plan is unchanged')
    result = json.loads(process.stdout)
    return result['candidates'], result['statuses']


ROOT = Path(__file__).resolve().parents[2]
VENDORED = ROOT / "vendor" / "trackspace" / "engine.js"
SCHEDULER = VENDORED.with_name("scheduler.mjs")
CP_SAT_SOLVER = VENDORED.with_name("solver.py")
# Bump this whenever the embedded validation semantics change.  The Streamlit
# app uses it to discard cached plans that were built by an older runtime.
ENGINE_RULESET = "trackspace-cpsat-complete-diagnostics-alternatives-v2"
MIN_NODE = 20                   # the supplied handoff requires Node 20+


class TrackspaceUnavailable(RuntimeError):
    """Node or the engine is missing, so this planner cannot run here."""


def _engine_path() -> Path:
    """Return only the checked-in handoff engine.

    External working copies must never replace the code that produced the
    displayed conflicts, maps, scores and downloadable CSV files.
    """
    if all(p.is_file() for p in (VENDORED, SCHEDULER, CP_SAT_SOLVER,
                                VENDORED.with_name("request-diagnostics.mjs"),
                                VENDORED.with_name("check-request-groups.py"))):
        return VENDORED
    raise TrackspaceUnavailable(
        "Trackspace CP-SAT handoff files are incomplete. Expected engine.js, "
        "scheduler.mjs, solver.py, request-diagnostics.mjs and "
        "check-request-groups.py under vendor/trackspace/.")


def node_version() -> int | None:
    """Major version of the node on PATH, or None if there isn't one."""
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True,
                             timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    raw = (out.stdout or "").strip().lstrip("v").split(".")[0]
    return int(raw) if raw.isdigit() else None


def engine_description() -> str:
    """Describe the single checked-in Trackspace runtime in use."""
    try:
        engine = _engine_path()
    except TrackspaceUnavailable as exc:
        return str(exc)
    return f"{engine} (vendored handoff), CP-SAT scheduler"


def availability() -> tuple[bool, str]:
    """Whether this planner can run here, and in plain words why not."""
    try:
        engine = _engine_path()
    except TrackspaceUnavailable as exc:
        return False, str(exc)
    major = node_version()
    if major is None:
        return False, ("Node.js is not installed on this machine. The Trackspace "
                       "planner is JavaScript and needs it. On Streamlit Cloud, "
                       "listing 'nodejs' in packages.txt installs it.")
    if major < MIN_NODE:
        return False, (f"Node.js {major} is too old for the Trackspace engine; "
                       f"{MIN_NODE} or newer is required.")
    try:
        check = subprocess.run([sys.executable, "-c",
                                "from ortools.sat.python import cp_model"],
                               capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        check = None
    if not check or check.returncode:
        return False, ("OR-Tools is not available for the Trackspace CP-SAT "
                       "scheduler. Install the project's requirements.txt.")
    return True, f"Trackspace CP-SAT handoff at {engine}, Node.js {major}"


def requested_conflicts(data_dir: str | Path) -> list[Conflict]:
    """Diagnose the requested dates with the Trackspace rule engine.

    This has deliberately no solver fallback.  If the A/B/C engine is not
    available, claiming that a different Python interpretation is Trackspace
    aligned would be misleading.
    """
    ok, why = availability()
    if not ok:
        raise TrackspaceUnavailable(why)
    process = subprocess.run(
        ["node", "--input-type=module", "-e", _REQUEST_CONFLICT_RUNNER,
         str(_engine_path()), str(Path(data_dir)), sys.executable],
        capture_output=True, text=True, timeout=130,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Trackspace conflict scan failed")
    try:
        raw = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Trackspace conflict scan returned invalid output") from exc
    if raw.get("type") != "conflicts":
        raise RuntimeError("Trackspace conflict scan did not return conflicts")
    return [Conflict(kind=str(c["kind"]), week=int(c["week"]),
                     where=str(c.get("where", "")),
                     parties=[str(a) for a in c.get("parties", [])],
                     contracts=[str(n) for n in c.get("contracts", [])],
                     detail=str(c.get("detail", "")),
                     options=[str(o) for o in c.get("options", [])],
                     severity=str(c.get("severity", "blocking")),
                     need=int(c.get("need", 0)), supply=int(c.get("supply", 0)))
            for c in raw.get("conflicts", [])]


def requested_pressure(data_dir: str | Path) -> list[Conflict]:
    """Check requested consecutive standard accesses with the handoff rules."""
    return requested_conflicts(data_dir)


def solve_trackspace(data_dir: str | Path, scenario: str, progress=None,
                     seconds: float = 120.0, alternative_count: int = 0) -> TrackspaceOutcome:
    """Run the supplied CP-SAT scheduler and revalidate its returned schedule."""
    ok, why = availability()
    if not ok:
        raise TrackspaceUnavailable(why)
    started = time.monotonic()
    if not isinstance(alternative_count, int) or not 0 <= alternative_count <= 3:
        raise ValueError("Alternative count must be between 0 and 3")
    limit = max(1.0, min(float(seconds), 600.0))
    if progress:
        progress({"iteration": 0, "total": 1, "stage": "CP-SAT search"})
    try:
        process = subprocess.run(
            ["node", "--input-type=module", "-e", _CP_SAT_RUNNER,
             str(SCHEDULER), str(_engine_path()), str(Path(data_dir)),
             scenario.upper(), sys.executable, str(limit), str(alternative_count)],
            capture_output=True, text=True, timeout=limit + alternative_count*15 + 70,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Trackspace CP-SAT search timed out") from exc
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Trackspace CP-SAT scheduler failed")
    raw = None
    for line in process.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "progress" and progress:
            progress(event["info"])
        elif event.get("type") == "result":
            raw = event
    if raw is None:
        raise RuntimeError("Trackspace CP-SAT scheduler returned no result")
    report = raw.get("report") or {
        "feasible": False, "hard_violations": [], "score": None,
        "results": [], "completed_activities": 0,
        "contracts_overrunning": 0, "overrun_days_total": 0,
        "eclo_nights_total": 0, "excess_access_nights_total": 0,
        "utilization": [],
    }
    solver = raw.get("solver") or {}
    status = str(raw.get("status") or solver.get("status") or "UNKNOWN")
    bound = float(solver.get("bound", float("nan")))
    optimality = {
        "status": status,
        "lower_bound": bound,
        "matches_bound": status == "OPTIMAL",
        "model_limited": True,
        "alternative_search_status": raw.get("alternativeSearchStatus", []),
        "alternative_search_requested": alternative_count > 0,
    }
    # Do not present a partial candidate as a usable schedule. The comparison
    # table can still name it as infeasible through the status and report.
    if not report["feasible"]:
        return TrackspaceOutcome(Submission(), status, float("nan"), bound,
                                 time.monotonic() - started,
                                 int(raw.get("schedule_end", 1)), report,
                                 True, [], optimality, raw.get("csvFiles"))
    sub = Submission(
        accesses=[Access(r["activity_id"], int(r["access_seq"]), int(r["week"]),
                         bool(r["eclo"]), int(r["access_night"]))
                  for r in raw["schedule"]],
        occupancies=[Occupancy(r["activity_id"], int(r["week"]), r["location_id"],
                               r["co_share_group"])
                     for r in raw["occupancy"]],
        results=[Result(r["scenario"], r["contract_number"],
                        date.fromisoformat(r["simulated_completion_date"]),
                        int(r["overrun_days"]))
                 for r in report["results"] if r["simulated_completion_date"]],
    )
    score = float(report["score"] if report["score"] is not None else float("nan"))
    return TrackspaceOutcome(sub, status, score, bound,
                             time.monotonic() - started,
                             int(raw["schedule_end"]), report,
                             True, raw.get("alternatives", []), optimality, raw.get("csvFiles"))
