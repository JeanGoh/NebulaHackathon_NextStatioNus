"""Independent validator. Deliberately shares no constraint code with the solver.

The reference validator does not ship with the problem pack. This is our
reconstruction from PS1_README.md sections 2.4-2.7, calibrated so that the
known-feasible sample submission returns zero hard violations under Scenario A.

Where the brief is ambiguous, the choice is exposed on `Policy` rather than
buried, and the reasoning is recorded in docs/SPEC.md.
"""
from __future__ import annotations

import collections
import itertools
from dataclasses import dataclass, field

from .model import Instance
from .network import Network
from .submission import Submission

CONTRACT_WEIGHT = {1: 100.0, 2: 10.0, 3: 1.0}
ACTIVITY_NUDGE = {1: 0.3, 2: 0.2, 3: 0.0}
EXCESS_NIGHT_COST = 7.0
ECLO_COST = 5.0


@dataclass(frozen=True)
class Policy:
    """Interpretations the brief leaves open. Defaults reproduce the sample."""

    # Buffers are measured in sectors. Do they also bite on station platforms?
    buffer_bites_platforms: bool = False
    # Does a buffer push only other buffer-carrying work (Live / Non-live Consist)?
    buffer_pushes_carriers_only: bool = True
    # Two activities sharing a location on different nights are separated in
    # time, so no spatial buffer is needed between them.
    overlap_implies_separated: bool = True
    # priority_weighted_score sums "per overrunning activity" -- but is an
    # activity's overrun measured from its OWN last week, or its contract's?
    # The brief supports both. Spread on the sample is 48.3 vs 137.9.
    overrun_basis: str = "activity"          # "activity" | "contract"


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: str
    detail: str

    def as_dict(self) -> dict:
        return {"rule": self.rule, "severity": self.severity, "detail": self.detail}


@dataclass
class Report:
    scenario: str
    feasible: bool
    hard_violations: list[Violation] = field(default_factory=list)
    soft_scores: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "feasible": self.feasible,
            "hard_violations": [v.as_dict() for v in self.hard_violations],
            "soft_scores": self.soft_scores,
            "detail": self.detail,
        }


def validate(inst: Instance, sub: Submission, scenario: str | None = None,
             policy: Policy = Policy()) -> Report:
    scenario = (scenario or sub.scenario).upper()
    if scenario not in ("A", "B", "C"):
        raise ValueError(f"unknown scenario {scenario!r}")
    net = Network(inst)
    V: list[Violation] = []

    acc_by_act = collections.defaultdict(list)
    for a in sub.accesses:
        acc_by_act[a.activity_id].append(a)
    weeks_of = {a: sorted({x.week for x in xs}) for a, xs in acc_by_act.items()}

    # --- rule 1: workload conservation ---------------------------------
    for aid, act in inst.activities.items():
        got = sum(x.work_units for x in acc_by_act.get(aid, []))
        if not acc_by_act.get(aid):
            V.append(Violation("workload", "hard", f"{aid}: not scheduled at all"))
        elif got + 1e-9 < act.total_accesses:
            V.append(Violation("workload", "hard",
                               f"{aid}: yields {got} < total_accesses {act.total_accesses}"))
    for aid in acc_by_act:
        if aid not in inst.activities:
            V.append(Violation("workload", "hard", f"{aid}: not an activity in this instance"))

    # --- rule 2: planned start week -------------------------------------
    for aid, xs in acc_by_act.items():
        if aid not in inst.activities:
            continue
        earliest = inst.week_of(inst.activities[aid].planned_start_date)
        for x in xs:
            if x.week < earliest:
                V.append(Violation("start_date", "hard",
                                   f"wk{x.week}: {aid} starts before planned start week {earliest}"))
        if len({x.week for x in xs}) != len(xs):
            V.append(Violation("allocation", "hard",
                               f"{aid}: more than one access in the same week"))

    # --- rule 3: precedence ---------------------------------------------
    for aid, act in inst.activities.items():
        pred = act.predecessor_activity_id
        if pred and weeks_of.get(aid) and weeks_of.get(pred):
            if weeks_of[aid][0] <= weeks_of[pred][-1]:
                V.append(Violation("precedence", "hard",
                                   f"{aid} starts wk{weeks_of[aid][0]} but predecessor "
                                   f"{pred} runs to wk{weeks_of[pred][-1]}"))

    # --- occupancy consistency ------------------------------------------
    occ_map: dict[int, dict[str, dict[str, str]]] = collections.defaultdict(dict)
    for o in sub.occupancies:
        occ_map[o.week].setdefault(o.activity_id, {})[o.location_id] = o.co_share_group
    for aid, xs in acc_by_act.items():
        if aid not in inst.activities:
            continue
        expected = set(net.expand(aid))
        for x in xs:
            got = set(occ_map[x.week].get(aid, {}))
            if got != expected:
                V.append(Violation("occupancy", "hard",
                                   f"wk{x.week}: {aid} occupancy {sorted(got - expected)} unexpected / "
                                   f"{sorted(expected - got)} missing"))

    # --- rule 5 + capacity: possessions per location-week ----------------
    groups = collections.defaultdict(set)
    members = collections.defaultdict(set)
    for o in sub.occupancies:
        groups[(o.location_id, o.week)].add(o.co_share_group)
        members[(o.location_id, o.week, o.co_share_group)].add(o.activity_id)

    excess_total = 0
    for (loc, wk), gs in sorted(groups.items()):
        if loc not in inst.locations:
            V.append(Violation("capacity", "hard", f"wk{wk}: unknown location {loc}"))
            continue
        cap = inst.locations[loc].supply_capacity
        excess = max(0, len(gs) - cap)
        excess_total += excess
        if excess and scenario == "A":
            V.append(Violation("capacity", "hard",
                               f"wk{wk}: {loc} uses {len(gs)} possessions, supply is {cap}"))
        elif excess > 1 and scenario == "C":
            V.append(Violation("capacity", "hard",
                               f"wk{wk}: {loc} exceeds supply by {excess} (C allows 1)"))

    for (loc, wk, grp), acts in sorted(members.items()):
        types = collections.Counter(
            inst.contracts[inst.activities[a].contract_number].access_type
            for a in acts if a in inst.activities)
        n_pm, n_pc, n_c = types.get("PM", 0), types.get("PC", 0), types.get("C", 0)
        legal = (n_pm == 1 and n_pc == 0 and n_c == 0) or \
                (n_pm == 0 and n_pc <= 1 and n_pc + n_c <= 4)
        if not legal:
            V.append(Violation("mix", "hard",
                               f"wk{wk}: {loc}/{grp} illegal mix PM={n_pm} PC={n_pc} C={n_c}"))

    # --- rules 7 & 8: weekly allocation and workfronts -------------------
    bucket = collections.defaultdict(lambda: collections.defaultdict(set))
    for a in sub.accesses:
        act = inst.activities.get(a.activity_id)
        if act:
            bucket[(act.contract_number, act.activity_type, a.week)][a.access_night].add(a.activity_id)
    for (cn, at, wk), nights in sorted(bucket.items()):
        c = inst.contracts[cn]
        if len(nights) > c.max_access_per_week:
            V.append(Violation("allocation", "hard",
                               f"wk{wk}: {cn}/{at} uses {len(nights)} nights, cap {c.max_access_per_week}"))
        for n, acts in sorted(nights.items()):
            if len(acts) > c.number_of_workfronts:
                V.append(Violation("workfront", "hard",
                                   f"wk{wk}: {cn}/{at} night {n} runs {len(acts)} activities, "
                                   f"workfronts {c.number_of_workfronts}"))
        for n in nights:
            if not 1 <= n <= c.max_access_per_week:
                V.append(Violation("allocation", "hard",
                                   f"wk{wk}: {cn}/{at} access_night {n} out of range"))

    # --- rule 4: closures and buffers ------------------------------------
    V += _check_buffers(inst, net, occ_map, policy)

    # --- rules 8/9: ECLO --------------------------------------------------
    eclo_nights = [a for a in sub.accesses if a.eclo]
    if scenario == "A" and eclo_nights:
        V.append(Violation("eclo", "hard",
                           f"Scenario A forbids ECLO; {len(eclo_nights)} ECLO accesses present"))
    if scenario == "C":
        V += _check_eclo_window(inst, net, eclo_nights)

    # --- soft scores ------------------------------------------------------
    soft, results_detail = _score(inst, sub, acc_by_act, excess_total,
                                  len(eclo_nights), scenario, policy)

    # --- Scenario B: overrun is hard --------------------------------------
    if scenario == "B":
        for cn, over in results_detail["contract_overrun"].items():
            if over > 0:
                V.append(Violation("planned_date", "hard",
                                   f"{cn}: overruns planned completion by {over} days "
                                   f"(Scenario B forbids any overrun)"))

    feasible = not V
    if feasible:
        if scenario == "A":
            soft["objective_score"] = soft["priority_weighted_score"]
        elif scenario == "B":
            soft["objective_score"] = (EXCESS_NIGHT_COST * soft["excess_access_nights_total"]
                                       + ECLO_COST * soft["eclo_nights_total"])
        else:
            soft["objective_score"] = (soft["priority_weighted_score"]
                                       + EXCESS_NIGHT_COST * soft["excess_access_nights_total"]
                                       + ECLO_COST * soft["eclo_nights_total"])
        soft["formula_version"] = "ps1-v1"

    hotspots = [f"{loc}@wk{wk}" for (loc, wk), gs in groups.items()
                if loc in inst.locations and len(gs) >= inst.locations[loc].supply_capacity]
    return Report(
        scenario=scenario, feasible=feasible, hard_violations=V, soft_scores=soft,
        detail={"capacity_hotspots": sorted(hotspots)[:50],
                "nights_scheduled": len(sub.accesses),
                "eclo_nights": len(eclo_nights)},
    )


def _check_buffers(inst, net, occ_map, policy: Policy) -> list[Violation]:
    """Only Live / Non-live (Consist) project a buffer, and (by default) only
    such work is pushed by one. Buffers are measured in sectors."""
    out: list[Violation] = []
    occupied: dict[str, set[str]] = {}
    ring: dict[str, set[str]] = {}
    for aid in inst.activities:
        locs = set(net.expand(aid))
        occupied[aid] = locs
        ring[aid] = set(net.buffer_locations(aid, sorted(locs)))
    carries = {aid for aid in inst.activities if ring[aid]}
    keep = (lambda s: s) if policy.buffer_bites_platforms \
        else (lambda s: {l for l in s if l.startswith("SEC:")})

    for wk, acts in sorted(occ_map.items()):
        present = [a for a in acts if a in inst.activities]
        for A, B in itertools.permutations(present, 2):
            if A not in carries:
                continue
            if policy.buffer_pushes_carriers_only and B not in carries:
                continue
            ga, gb = occ_map[wk].get(A, {}), occ_map[wk].get(B, {})
            shared = set(ga) & set(gb)
            if any(ga[l] == gb[l] for l in shared):
                continue                       # same possession: mutually exempt
            if policy.overlap_implies_separated and shared:
                continue                       # provably on different nights
            clash = keep(ring[A]) & keep(occupied[B])
            if clash:
                out.append(Violation("closure", "hard",
                                     f"wk{wk}: {B} inside closure of ['{A}'] at {sorted(clash)}"))
    return out


def _check_eclo_window(inst, net, eclo_accesses) -> list[Violation]:
    """Scenario C: each line's ECLO nights must fall in one span of <= 2 weeks."""
    out: list[Violation] = []
    per_line = collections.defaultdict(list)
    for a in eclo_accesses:
        if a.activity_id not in inst.activities:
            continue
        for loc in net.expand(a.activity_id):
            per_line[loc.split(":")[1]].append(a.week)
    for line, weeks in sorted(per_line.items()):
        if weeks and max(weeks) - min(weeks) + 1 > 2:
            out.append(Violation("eclo", "hard",
                                 f"line {line}: ECLO nights span wk{min(weeks)}-wk{max(weeks)}, "
                                 f"window is 2 weeks"))
    return out


def _score(inst, sub, acc_by_act, excess_total, eclo_total, scenario, policy=None):
    policy = policy or Policy()
    last_week_contract = collections.defaultdict(int)
    last_week_activity = {}
    for aid, xs in acc_by_act.items():
        if aid not in inst.activities:
            continue
        lw = max(x.week for x in xs)
        last_week_activity[aid] = lw
        cn = inst.activities[aid].contract_number
        last_week_contract[cn] = max(last_week_contract[cn], lw)

    overrun_total = earliness_total = 0
    overrunning = 0
    contract_overrun = {}
    for cn, c in inst.contracts.items():
        lw = last_week_contract.get(cn)
        if lw is None:
            contract_overrun[cn] = 0
            continue
        sim = inst.week_end(lw)
        over = max(0, (sim - c.planned_completion_date).days)
        early = max(0, (c.planned_completion_date - sim).days)
        contract_overrun[cn] = over
        overrun_total += over
        earliness_total += early
        overrunning += 1 if over else 0

    priority_overrun = {"1": 0, "2": 0, "3": 0}
    weighted = 0.0
    for aid, lw in last_week_activity.items():
        act = inst.activities[aid]
        c = inst.contracts[act.contract_number]
        basis = lw if policy.overrun_basis == "activity" \
            else last_week_contract[act.contract_number]
        over = max(0, (inst.week_end(basis) - c.planned_completion_date).days)
        if not over:
            continue
        priority_overrun[str(c.contract_priority)] += over
        weighted += CONTRACT_WEIGHT[c.contract_priority] * \
            (1 + ACTIVITY_NUDGE[act.activity_priority]) * over

    soft = {
        "scenario": scenario,
        "overrun_days_total": overrun_total,
        "contracts_overrunning": overrunning,
        "earliness_days_total": earliness_total,
        "excess_access_nights_total": excess_total,
        "eclo_nights_total": eclo_total,
        "priority_overrun": priority_overrun,
        "priority_weighted_score": round(weighted, 2),
    }
    return soft, {"contract_overrun": contract_overrun}
