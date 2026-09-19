"""Conflicts between maintenance requests, as submitted.

Contractors lodge what they want without seeing each other's requests. Taken at
face value — every job starting the week it asked for and running straight
through — those requests collide. This module finds the collisions, names the
parties, and says what can be done about each one.

Nothing here is a guess: every conflict is a rule from docs/SPEC.md evaluated
against the requested dates.
"""
from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field

from .model import Instance
from .network import Network
from .validate import Policy

KIND_LABEL = {
    "contention": "Teams must share a worksite",
    "capacity": "Too many teams want the same worksite",
    "buffer": "Safety buffers overlap",
    "weekly_limit": "Contractor over their weekly allowance",
    "workfronts": "Too many simultaneous workfronts",
    "horizon": "Work extends beyond the planning horizon",
    "precedence": "Job scheduled before the one it depends on",
    "mix": "Incompatible working arrangement",
}


@dataclass
class Conflict:
    kind: str
    week: int
    where: str                      # location_id, or "" when not location-bound
    parties: list[str]              # activity ids
    contracts: list[str]
    detail: str
    options: list[str] = field(default_factory=list)
    severity: str = "blocking"      # "blocking" | "coordination"
    # For a location-week: the fewest possessions any plan could do this with,
    # and how many that worksite nominally has. need > supply is provable --
    # no ordering of the work makes it fit. Zero means "not a supply finding".
    need: int = 0
    supply: int = 0

    @property
    def label(self) -> str:
        return KIND_LABEL.get(self.kind, self.kind)


def as_requested(inst: Instance) -> dict[str, list[int]]:
    """Each job starting the week it asked for, running consecutive weeks."""
    out = {}
    for aid, a in inst.activities.items():
        sw = inst.week_of(a.planned_start_date)
        out[aid] = [w for w in range(sw, sw + a.total_accesses)
                    if w <= inst.horizon_weeks]
    return out


def _possessions_needed(types: collections.Counter) -> int:
    n_pm, n_pc, n_c = types.get("PM", 0), types.get("PC", 0), types.get("C", 0)
    spare = max(0, n_c - 3 * n_pc)
    return n_pm + n_pc + math.ceil(spare / 4)


def detect(inst: Instance, requested: dict[str, list[int]] | None = None,
           policy: Policy = Policy()) -> list[Conflict]:
    req = requested or as_requested(inst)
    net = Network(inst)
    occ = {a: set(net.expand(a)) for a in inst.activities}
    ring = {a: set(net.buffer_locations(a, sorted(occ[a]))) for a in inst.activities}
    carries = {a for a in inst.activities if ring[a]}
    keep = (lambda s: s) if policy.buffer_bites_platforms \
        else (lambda s: {l for l in s if l.startswith("SEC:")})
    typ = lambda a: inst.contracts[inst.activities[a].contract_number].access_type
    con = lambda a: inst.activities[a].contract_number

    at = collections.defaultdict(list)              # (loc, week) -> activities
    in_week = collections.defaultdict(list)         # week -> activities
    for aid, ws in req.items():
        for w in ws:
            in_week[w].append(aid)
            for loc in occ[aid]:
                at[(loc, w)].append(aid)

    out: list[Conflict] = []

    # 1. more possessions wanted than the worksite can open
    for (loc, w), aids in sorted(at.items()):
        cap = inst.locations[loc].supply_capacity
        need = _possessions_needed(collections.Counter(typ(a) for a in aids))
        if need > cap:
            out.append(Conflict(
                "capacity", w, loc, sorted(aids), sorted({con(a) for a in aids}),
                f"{', '.join(sorted({inst.contracts[con(a)].contract_description for a in aids}))} "
                f"all want this worksite in week {w} — {need} separate possessions "
                f"needed, but it opens only {cap} a week.",
                [f"Move {a} to a later week" for a in sorted(aids)[:3]]
                + (["Pack compatible teams into one possession"]
                   if any(typ(a) == "C" for a in aids) else [])))

    # 1b. worksites where teams can fit only by sharing a possession
    for (loc, w), aids in sorted(at.items()):
        if len(aids) < 2:
            continue
        cap = inst.locations[loc].supply_capacity
        need = _possessions_needed(collections.Counter(typ(a) for a in aids))
        if need > cap:
            continue                                   # already a blocking conflict
        if len(aids) > cap:
            out.append(Conflict(
                "contention", w, loc, sorted(aids), sorted({con(a) for a in aids}),
                f"{len(aids)} teams from {len(set(con(a) for a in aids))} contract(s) "
                f"want this worksite in week {w}. It opens {cap} possession(s), so they "
                f"can only all work if they share one.",
                ["Pack them into a shared possession (the plan does this)",
                 f"Give one team sole use and defer the rest"],
                severity="coordination"))

    # 2. exclusion zones colliding
    for w, aids in sorted(in_week.items()):
        for i, a in enumerate(sorted(aids)):
            if a not in carries:
                continue
            for b in sorted(aids)[i + 1:]:
                if policy.buffer_pushes_carriers_only and b not in carries:
                    continue
                if policy.overlap_implies_separated and (occ[a] & occ[b]):
                    continue
                clash = keep(ring[a]) & keep(occ[b])
                if clash:
                    out.append(Conflict(
                        "buffer", w, sorted(clash)[0], [a, b],
                        sorted({con(a), con(b)}),
                        f"{a} is {inst.contracts[con(a)].nature_of_activity} work, so it "
                        f"must keep {sorted(clash)[0]} clear in week {w} — but {b} is "
                        f"booked to work there.",
                        [f"Move {b} to another week",
                         f"Move {a} to another week",
                         "Run them on the same night as one shared possession"]))

    # 3. contractor over their weekly allowance
    for w, aids in sorted(in_week.items()):
        bucket = collections.defaultdict(list)
        for a in aids:
            act = inst.activities[a]
            bucket[(act.contract_number, act.activity_type)].append(a)
        for (cn, at_), members in sorted(bucket.items()):
            c = inst.contracts[cn]
            cap = c.max_access_per_week * c.number_of_workfronts
            if len(members) > cap:
                out.append(Conflict(
                    "weekly_limit", w, "", sorted(members), [cn],
                    f"{cn} has {len(members)} jobs running in week {w}, but is allowed "
                    f"{c.max_access_per_week} nights a week with "
                    f"{c.number_of_workfronts} team(s) — {cap} jobs at most.",
                    [f"Defer {a}" for a in sorted(members)[cap:]]
                    + ["Negotiate more access-nights for this contract"]))

    # 4. dependency order broken
    for aid, a in sorted(inst.activities.items()):
        p = a.predecessor_activity_id
        if p and req.get(aid) and req.get(p) and req[aid][0] <= req[p][-1]:
            out.append(Conflict(
                "precedence", req[aid][0], "", [aid, p], sorted({con(aid), con(p)}),
                f"{aid} is requested from week {req[aid][0]}, but it cannot start until "
                f"{p} finishes in week {req[p][-1]}.",
                [f"Start {aid} in week {req[p][-1] + 1} or later",
                 f"Bring {p} forward"]))
    return out


def summarise(conflicts: list[Conflict]) -> dict:
    by_kind = collections.Counter(c.kind for c in conflicts)
    parties = collections.Counter()
    for c in conflicts:
        for cn in c.contracts:
            parties[cn] += 1
    weeks = collections.Counter(c.week for c in conflicts)
    return {
        "total": len(conflicts),
        "by_kind": dict(by_kind),
        "worst_weeks": weeks.most_common(5),
        "most_involved": parties.most_common(5),
    }


def resolution(conflict: Conflict, requested: dict[str, list[int]],
               planned: dict[str, list[int]]) -> str:
    """How the built plan actually dealt with this conflict."""
    moves = []
    for a in conflict.parties:
        was, now = requested.get(a, []), planned.get(a, [])
        if was != now:
            w0 = f"wk {was[0]}–{was[-1]}" if was else "unscheduled"
            n0 = f"wk {now[0]}–{now[-1]}" if now else "unscheduled"
            moves.append(f"{a} moved {w0} → {n0}")
    if not moves:
        return "Resolved by packing the teams into a shared possession — nobody moved."
    return "; ".join(moves)
