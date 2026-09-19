"""One specific change, proposed — never applied without a yes.

The three-plan exercise replaces the whole schedule. That is the wrong tool
when a controller has one problem in one week and contractors already working
to the rest. What they need is the smallest change that fixes it, explained,
and a button that says yes.

So every proposal here starts by freezing the entire schedule in force and
unfreezing as little as possible, escalating only when the smaller change does
not work:

    level 0  nothing else moves
    level 1  only jobs touching the same worksites in the affected weeks
    level 2  those plus the rest of the same contract
    level 3  anything, anchored to the current dates (last resort)

The first level that produces a safe schedule is the proposal. What moved is
reported exactly, and applying it is a separate step the planner takes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import names as N
from .model import Instance
from .network import Network
from .solve import SolverConfig, solve
from .submission import Submission
from .validate import validate
from .whatif import Change, JobSpec, diff, weeks_by_activity, with_extra_job


@dataclass
class Proposal:
    goal: str                       # what was asked, in plain words
    ok: bool
    level: int                      # how far we had to escalate (0 = nothing else moved)
    summary: str                    # one sentence a controller can say yes or no to
    steps: list[str]                # the concrete changes, in order
    moved: list[Change]
    new_weeks: list[int]            # where the requested/targeted job now sits
    score_change: float
    submission: Submission | None   # the schedule if applied
    instance: Instance | None       # the instance the submission belongs to
    why_not: str = ""               # when ok is False


def _neighbours(inst: Instance, net: Network, sub: Submission,
                locs: set[str], weeks: set[int]) -> set[str]:
    """Jobs on these worksites in these weeks — the ones a local change may touch."""
    out = set()
    for o in sub.occupancies:
        if o.week in weeks and o.location_id in locs:
            out.add(o.activity_id)
    return out


def _levels(inst, net, sub, target_locs, target_weeks, contract, exclude):
    every = {a for a in inst.activities} - exclude
    l1 = _neighbours(inst, net, sub, target_locs, target_weeks) - exclude
    l2 = l1 | {a for a in every if inst.activities[a].contract_number == contract}
    return [set(), l1, l2, every]


def _on_time_contracts(inst: Instance, sub: Submission) -> set[str]:
    """Contracts that the live plan already gets over the line on time."""
    last = {}
    for a in sub.accesses:
        if a.activity_id not in inst.activities:
            continue
        cn = inst.activities[a.activity_id].contract_number
        last[cn] = max(last.get(cn, 0), a.week)
    return {cn for cn, week in last.items()
            if inst.week_end(week) <= inst.contracts[cn].planned_completion_date}


def _run(inst2, sub, scenario, unfrozen, focus, seconds, focus_first=False):
    base = weeks_by_activity(sub)
    freeze = {a: set(w) for a, w in base.items() if a not in unfrozen}
    anchor = {a: set(w) for a, w in base.items()}
    out = solve(inst2, SolverConfig(scenario=scenario, max_seconds=seconds,
                                    freeze=freeze, anchor=anchor, focus=focus,
                                    focus_first=focus_first,
                                    protect_on_time_contracts=_on_time_contracts(inst2, sub)))
    if not out.submission.accesses:
        return None
    if not validate(inst2, out.submission, scenario).feasible:
        return None
    return out


def _score(inst, sub, scenario) -> float:
    s = validate(inst, sub, scenario).soft_scores
    return float(s.get("objective_score", s.get("priority_weighted_score", 0.0)))


def _describe_move(c: Change) -> str:
    """'week 24 → week 27', or 'weeks 24, 25 → weeks 26, 27' -- only what changed."""
    gone = sorted(set(c.before) - set(c.after))
    came = sorted(set(c.after) - set(c.before))
    def wk(ws):
        return ("week " if len(ws) == 1 else "weeks ") + ", ".join(map(str, ws))
    if gone and came:
        return f"{wk(gone)} → {wk(came)}"
    if came:
        return f"adds {wk(came)}"
    return f"drops {wk(gone)}"


def _narrate(inst, moved: list[Change], target: str, new_weeks: list[int],
             level: int, goal_done: str) -> tuple[str, list[str]]:
    steps = []
    for c in moved:
        steps.append(f"Move {N.job_short(inst, c.activity_id)}: {_describe_move(c)}.")
    if new_weeks:
        wk = (f"weeks {new_weeks[0]}–{new_weeks[-1]}" if len(new_weeks) > 1
              else f"week {new_weeks[0]}")
        steps.append(f"{goal_done} in {wk}.")
    if not moved:
        summary = f"{goal_done} with nothing else moving."
    elif len(moved) == 1:
        c = moved[0]
        summary = (f"Move {N.job_short(inst, c.activity_id)} by "
                   f"{abs(c.after[-1] - c.before[-1])} week(s); then {goal_done.lower()}.")
    else:
        summary = f"{goal_done}, at the cost of moving {len(moved)} other jobs."
    return summary, steps


def fit_request(inst: Instance, sub: Submission, scenario: str, spec: JobSpec,
                seconds: float = 15.0) -> Proposal:
    """The smallest change that takes an incoming request."""
    inst2 = with_extra_job(inst, spec)
    net = Network(inst2)
    target_locs = set(net.expand(spec.activity_id))
    target_weeks = set(range(spec.earliest_week,
                             min(inst.horizon_weeks, spec.earliest_week
                                 + spec.total_accesses + 2) + 1))
    goal = (f"Fit {spec.total_accesses} night(s) for {N.contract(inst, spec.contract_number)} "
            f"on the {N.place(spec.start_location_id)}"
            + ("" if spec.start_location_id == spec.end_location_id
               else f" to {N.place(spec.end_location_id).split(', ')[-1]}")
            + f", from week {spec.earliest_week}")
    base_score = _score(inst, sub, scenario)

    found = []
    for level, unfrozen in enumerate(_levels(inst, net, sub, target_locs, target_weeks,
                                             spec.contract_number, {spec.activity_id})):
        out = _run(inst2, sub, scenario, unfrozen | {spec.activity_id}, None, seconds)
        if out is None:
            continue
        moved = [c for c in diff(sub, out.submission, inst2)
                 if c.activity_id != spec.activity_id]
        new_weeks = weeks_by_activity(out.submission).get(spec.activity_id, [])
        cost = round(_score(inst2, out.submission, scenario) - base_score, 2)
        found.append((cost, level, moved, new_weeks, out))
        if level == 0 and cost <= 0:
            break                                      # free and undisturbed: done
    if found:
        cost, level, moved, new_weeks, out = min(found, key=lambda f: (f[0], f[1]))
        summary, steps = _narrate(inst2, moved, spec.activity_id, new_weeks, level,
                                  "The new work goes")
        quiet = next((f for f in found if f[1] == 0), None)
        if quiet and quiet[1] != level:
            steps.append(f"(Leaving everything else where it is would also work, "
                         f"but costs {quiet[0] - cost:+.1f} more — the new work would "
                         f"run to week {quiet[3][-1]}.)")
        return Proposal(goal, True, level, summary, steps, moved, new_weeks, cost,
                        out.submission, inst2)

    from .whatif import diagnose_rejection
    d = diagnose_rejection(inst, sub, spec, scenario, seconds=seconds)
    return Proposal(goal, False, 3, "This cannot be fitted in.", [], [], [], 0.0,
                    None, None, why_not=" ".join(d["reasons"]))


def pull_earlier(inst: Instance, sub: Submission, scenario: str, aid: str,
                 seconds: float = 15.0) -> Proposal:
    """The smallest change that brings one late job forward."""
    net = Network(inst)
    base = weeks_by_activity(sub)
    cur = base.get(aid, [])
    if not cur:
        return Proposal(f"Bring {N.job(inst, aid)} forward", False, 0,
                        "That job is not scheduled.", [], [], [], 0.0, None, None)
    a = inst.activities[aid]
    target_locs = set(net.expand(aid))
    target_weeks = set(range(inst.week_of(a.planned_start_date), cur[-1]))
    goal = f"Bring {N.job(inst, aid)} forward from week {cur[-1]}"
    base_score = _score(inst, sub, scenario)

    for level, unfrozen in enumerate(_levels(inst, net, sub, target_locs, target_weeks,
                                             a.contract_number, {aid})):
        out = _run(inst, sub, scenario, unfrozen | {aid}, aid, seconds,
                   focus_first=True)
        if out is None:
            continue
        new_weeks = weeks_by_activity(out.submission).get(aid, [])
        if new_weeks[-1] >= cur[-1]:
            continue                                  # no improvement at this level
        moved = [c for c in diff(sub, out.submission, inst) if c.activity_id != aid]
        summary, steps = _narrate(inst, moved, aid, new_weeks, level,
                                  f"{N.job_short(inst, aid)} finishes")
        return Proposal(goal, True, level, summary, steps, moved, new_weeks,
                        round(_score(inst, out.submission, scenario) - base_score, 2),
                        out.submission, inst)

    return Proposal(goal, False, 3, "It cannot be brought forward.", [], [], [], 0.0,
                    None, None,
                    why_not=f"Every earlier week is either before its planned start or "
                            f"has no safe slot on its worksites, even allowing other "
                            f"work to move.")


# ---------------------------------------------------------------------------
# What a proposal means on the ground, and a model's read of it.
# ---------------------------------------------------------------------------

def proposal_facts(inst: Instance, sub: Submission, pr: Proposal) -> dict:
    """Everything a controller needs to judge the change: where the target
    work lands, who it shares with, what its buffer closes, who else moves
    and who therefore has to be told. Deterministic; the model narrates this
    and may not add to it."""
    if not pr.ok or pr.submission is None:
        return {"possible": False, "why_not": pr.why_not, "goal": pr.goal}
    inst2 = pr.instance or inst
    net = Network(inst2)
    new_sub = pr.submission
    target = next((c.activity_id for c in diff(sub, new_sub, inst2)
                   if c.activity_id not in weeks_by_activity(sub)), None)
    if target is None:                                   # brought-forward case
        target = next((c.activity_id for c in diff(sub, new_sub, inst2)
                       if c.activity_id not in {m.activity_id for m in pr.moved}), None)

    group_of, at_loc = {}, {}
    for o in new_sub.occupancies:
        group_of[(o.activity_id, o.week, o.location_id)] = o.co_share_group
        at_loc.setdefault((o.location_id, o.week, o.co_share_group), set()).add(o.activity_id)

    def job_block(aid):
        a = inst2.activities[aid]
        c = inst2.contracts[a.contract_number]
        weeks = weeks_by_activity(new_sub).get(aid, [])
        locs = sorted(net.expand(aid))
        ring = sorted(set(net.buffer_locations(aid, locs)) - set(locs))
        shares = {}
        for w in weeks:
            for loc in locs:
                g = group_of.get((aid, w, loc))
                if g:
                    for other in at_loc.get((loc, w, g), set()) - {aid}:
                        shares.setdefault(w, set()).add(
                            inst2.contracts[inst2.activities[other].contract_number]
                            .contract_description)
        return {
            "job": aid, "contractor": c.contract_description,
            "priority": TIER_WORD(c.contract_priority),
            "work": c.nature_of_activity, "access_type": c.access_type,
            "weeks": weeks,
            "dates": [f"{inst2.week_start(w):%d %b}–{inst2.week_end(w):%d %b}" for w in weeks],
            "worksites": [N.place(l) for l in locs],
            "shares_possession_with": {w: sorted(v) for w, v in shares.items()},
            "keeps_clear": [N.place(l) for l in ring][:8],
            "eclo_nights": sum(1 for x in new_sub.accesses
                               if x.activity_id == aid and x.eclo),
        }

    moved = []
    for c in pr.moved:
        a = inst2.activities[c.activity_id]
        con = inst2.contracts[a.contract_number]
        moved.append({
            "job": c.activity_id, "contractor": con.contract_description,
            "priority": TIER_WORD(con.contract_priority),
            "from_weeks": c.before, "to_weeks": c.after,
            "change": _describe_move(c),
            "worksites": [N.place(l) for l in sorted(net.expand(c.activity_id))][:4],
        })

    return {
        "possible": True, "goal": pr.goal, "summary": pr.summary,
        "target": job_block(target) if target else None,
        "other_jobs_that_move": moved,
        "contractors_to_notify": sorted({m["contractor"] for m in moved}
                                        | ({job_block(target)["contractor"]} if target else set())),
        "cost_to_programme": pr.score_change,
        "cost_meaning": ("no contract finishes later and no extra closures are needed"
                         if abs(pr.score_change) < 1e-6 else
                         "positive means some work finishes later or more closures are "
                         "used; P1 lateness costs 100 per day, P2 10, P3 1"),
        "safety": "every rule re-checked on the amended schedule and passed",
        "how_found": ["nothing else moves", "only jobs on the same worksites those weeks",
                      "those plus the rest of the same contract",
                      "anything, kept as close to current dates as possible"][pr.level],
    }


def TIER_WORD(p: int) -> str:
    return {1: "P1 critical", 2: "P2 important", 3: "P3 routine"}[p]


PROPOSAL_SYSTEM = """You are briefing a rail works controller on ONE proposed change to
the track access schedule. You are given the facts of the change. You may not add
facts, invent jobs, weeks, worksites or numbers, or soften a risk.

Write for someone deciding in the next minute. Cover, in this order and briefly:
1. What the change is, in one sentence a contractor would understand.
2. Whether to do it and why -- take a position. Weigh what it gains against
   what it disturbs; a routine (P3) job moving a week is cheap, a critical (P1)
   job moving is not. If the honest answer is "only if X", say that.
3. What could go wrong on the night: shared possessions, buffers that close
   other worksites, early closures.
4. Who has to be told, by name of programme.

Plain English. No headings, no bullet lists longer than four. Under 170 words.
Refer to contractors by programme name; codes in brackets at most once."""


def narrate_proposal(facts: dict, model: str = "claude-sonnet-4-5") -> str:
    """A model's read of the proposal. Raises if no key; the caller degrades."""
    import json
    import os
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("pip install anthropic") from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=500, system=PROPOSAL_SYSTEM,
        messages=[{"role": "user",
                   "content": "FACTS:\n" + json.dumps(facts, indent=1, default=str)}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
