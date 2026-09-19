"""Add an urgent job to a live programme and see what it costs.

The re-plan is a full re-solve, not a patch: the new job has to satisfy every
safety rule alongside everything else. But the solver is anchored to the plan
already in force, so among all equally-good schedules it picks the one that
moves the least existing work.
"""
from __future__ import annotations

import collections
import copy
from dataclasses import dataclass
from datetime import date

from .model import Activity, Instance
from .submission import Submission


@dataclass
class JobSpec:
    activity_id: str
    contract_number: str
    start_location_id: str
    end_location_id: str
    total_accesses: int
    earliest_week: int
    activity_priority: int = 1


@dataclass
class Change:
    activity_id: str
    contract_number: str
    before: list[int]
    after: list[int]

    @property
    def moved_nights(self) -> int:
        return len(set(self.before) ^ set(self.after)) // 2 or \
            abs(len(self.before) - len(self.after))


def with_extra_job(inst: Instance, spec: JobSpec) -> Instance:
    """A copy of the instance with one more job in it."""
    if spec.contract_number not in inst.contracts:
        raise ValueError(f"unknown contract {spec.contract_number}")
    for loc in (spec.start_location_id, spec.end_location_id):
        if loc not in inst.locations:
            raise ValueError(f"unknown location {loc}")
    if spec.activity_id in inst.activities:
        raise ValueError(f"{spec.activity_id} already exists")

    new = copy.copy(inst)
    new.activities = dict(inst.activities)
    new.activities[spec.activity_id] = Activity(
        activity_id=spec.activity_id,
        contract_number=spec.contract_number,
        activity_type=inst.contracts[spec.contract_number].activity_type,
        start_location_id=spec.start_location_id,
        end_location_id=spec.end_location_id,
        total_accesses=spec.total_accesses,
        planned_start_date=inst.week_start(spec.earliest_week),
        predecessor_activity_id=None,
        activity_priority=spec.activity_priority,
    )
    return new


def weeks_by_activity(sub: Submission) -> dict[str, list[int]]:
    out = collections.defaultdict(list)
    for a in sub.accesses:
        out[a.activity_id].append(a.week)
    return {k: sorted(v) for k, v in out.items()}


def diff(before: Submission, after: Submission, inst: Instance) -> list[Change]:
    """Which existing jobs had to move, and to where."""
    b, a = weeks_by_activity(before), weeks_by_activity(after)
    changes = []
    for aid in sorted(set(b) | set(a)):
        wb, wa = b.get(aid, []), a.get(aid, [])
        if wb != wa:
            cn = inst.activities[aid].contract_number if aid in inst.activities else "?"
            changes.append(Change(aid, cn, wb, wa))
    return changes


def summarise(before_score: float, after_score: float, changes: list[Change],
              new_id: str) -> str:
    placed = any(c.activity_id == new_id for c in changes)
    moved = [c for c in changes if c.activity_id != new_id]
    if not placed:
        return "The new job could not be placed."
    delta = after_score - before_score
    cost = ("at no cost to the rest of the programme" if abs(delta) < 1e-6
            else f"costing {delta:+.1f} on the plan's score")
    if not moved:
        return f"{new_id} fits {cost}, and nothing else moves."
    nights = sum(len(set(c.before) ^ set(c.after)) for c in moved)
    return (f"{new_id} fits {cost}. {len(moved)} existing job(s) shift, "
            f"{nights} night(s) of work in total.")


@dataclass
class Option:
    label: str
    rationale: str
    fits: bool
    weeks: list[int]
    moved: list[Change]
    score_change: float
    eclo_nights: int
    safe: bool

    @property
    def disruption(self) -> int:
        return sum(len(set(c.before) ^ set(c.after)) for c in self.moved)


def placement_options(inst: Instance, sub, spec: JobSpec, scenario: str,
                      seconds: float = 20.0) -> list[Option]:
    """Two or three genuinely different ways to take an incoming request.

    Not re-runs of the same search: one refuses to disturb anything, one buys
    the earliest start it can, one simply takes the cheapest answer. A planner
    picks between real trade-offs rather than being handed a single verdict.
    """
    from .solve import SolverConfig, solve
    from .validate import validate

    inst2 = with_extra_job(inst, spec)
    base_weeks = weeks_by_activity(sub)
    anchor = {k: set(v) for k, v in base_weeks.items()}
    base_score = _score_of(inst, sub, scenario)

    recipes = [
        ("Slot it in — nothing else moves",
         "Every job already promised keeps its dates. The new work goes wherever "
         "there is room left.",
         dict(freeze=anchor)),
        ("Start it as early as possible",
         "Buys the earliest start the rules allow, shifting other work only where "
         "it has to.",
         dict(anchor=anchor, focus=spec.activity_id)),
        ("Cheapest for the programme overall",
         "Lets the plan settle wherever it costs least, keeping disturbance to a "
         "minimum at that cost.",
         dict(anchor=anchor)),
    ]

    seen, out = set(), []
    for label, rationale, kw in recipes:
        res = solve(inst2, SolverConfig(scenario=scenario, max_seconds=seconds, **kw))
        if not res.submission.accesses:
            out.append(Option(label, rationale, False, [], [], float("nan"), 0, False))
            continue
        ws = weeks_by_activity(res.submission)
        placed = ws.get(spec.activity_id, [])
        moved = [c for c in diff(sub, res.submission, inst2)
                 if c.activity_id != spec.activity_id]
        key = (tuple(placed), tuple(sorted((c.activity_id, tuple(c.after))
                                           for c in moved)))
        if key in seen:                       # identical to an earlier option
            continue
        seen.add(key)
        out.append(Option(
            label, rationale, bool(placed), placed, moved,
            round(_score_of(inst2, res.submission, scenario) - base_score, 2),
            sum(1 for a in res.submission.accesses if a.eclo),
            validate(inst2, res.submission, scenario).feasible))
    return out


def _score_of(inst, sub, scenario) -> float:
    from .validate import validate
    s = validate(inst, sub, scenario).soft_scores
    return float(s.get("objective_score", s.get("priority_weighted_score", 0.0)))


def diagnose_rejection(inst: Instance, sub, spec: JobSpec, scenario: str,
                       seconds: float = 15.0) -> dict:
    """When no option fits, say why — and whether another plan would take it.

    A flat refusal is useless to a controller. The two things worth knowing are
    whether the request is impossible in itself, and whether it is only this
    plan's policy that rejects it.
    """
    from .solve import SolverConfig, solve
    from .validate import validate

    c = inst.contracts[spec.contract_number]
    deadline_wk = inst.week_of(c.planned_completion_date)
    reasons, remedies = [], []

    # 1. Can it finish in time at all, alone, with nothing else on the railway?
    eclo_cap = {"A": 0, "C": 2, "B": 99}[scenario.upper()]
    need = spec.total_accesses
    weeks_needed = next(w for w in range(1, 60)
                        if w + 0.5 * min(w, eclo_cap) >= need - 1e-9)
    finish = spec.earliest_week + weeks_needed - 1
    if finish > deadline_wk:
        over = (finish - deadline_wk) * 7
        reasons.append(
            f"{spec.contract_number} is due by the end of week {deadline_wk}, but "
            f"{need} nights starting no earlier than week {spec.earliest_week} "
            f"cannot finish before week {finish} — {over} days late. Under this "
            f"plan no contract may overrun, so it is refused.")
        remedies.append(f"Start it by week {max(1, deadline_wk - weeks_needed + 1)} "
                        f"instead of week {spec.earliest_week}")
        remedies.append(f"Split it: {max(1, deadline_wk - spec.earliest_week + 1)} "
                        f"nights now, the rest under a later contract period")
    if finish > inst.horizon_weeks:
        reasons.append(f"It would also run past the end of the {inst.horizon_weeks}-week "
                       f"programme.")

    # 2. Would another plan take it?
    accepts = []
    inst2 = with_extra_job(inst, spec)
    for name, code in (("Protect the track", "A"), ("Hit every deadline", "B"),
                       ("Balanced", "C")):
        if code == scenario.upper():
            continue
        res = solve(inst2, SolverConfig(scenario=code, max_seconds=seconds))
        if res.submission.accesses and validate(inst2, res.submission, code).feasible:
            placed = weeks_by_activity(res.submission).get(spec.activity_id, [])
            if placed:
                accepts.append((name, placed))

    if not reasons:
        reasons.append("No arrangement of the programme could take this request "
                       "without breaking a safety rule — most likely the worksites "
                       "it needs are already full for every week it could run.")
        remedies.append("Try fewer nights, a later earliest start, or a shorter section")

    return {"reasons": reasons, "remedies": remedies,
            "other_plans_that_accept": accepts}
