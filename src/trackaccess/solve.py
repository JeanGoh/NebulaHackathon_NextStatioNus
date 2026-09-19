"""CP-SAT solver.

Decision structure, derived from the output schema rather than invented:
an activity gets at most one access per week (stated in the brief, confirmed
across all 192 rows of the sample), so the core variable is simply
"does activity a work in week w".  Everything else -- access_night indices and
co_share_group labels -- is accounting that can be assigned after the fact
without changing feasibility, so it is left out of the model and filled in
during post-processing.
"""
from __future__ import annotations

import collections
import math
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .model import Instance
from .network import Network
from .submission import Access, Occupancy, Result, Submission
from .validate import ACTIVITY_NUDGE, CONTRACT_WEIGHT, Policy

SCALE = 10          # integerises the +0.3 / +0.2 activity-priority nudges


@dataclass
class SolverConfig:
    scenario: str = "A"
    max_seconds: float = 60.0
    # Keep the interactive planner responsive. A fixed seed improves
    # repeatability; audit callers can explicitly set workers=1 when they
    # require a fully reproducible run.
    workers: int = 8
    random_seed: int = 1
    policy: Policy = None           # which rule reading to solve against
    anchor: dict = None             # activity -> weeks of an existing plan; the
                                    # re-solve keeps to it wherever it is free to
    freeze: dict = None             # activity -> weeks that MUST NOT change
    protect_on_time_contracts: set | None = None
                                    # contracts that must remain on time during a re-plan
    focus: str = None               # an activity to pull as early as possible
    focus_first: bool = False       # earliness for `focus` outranks the score --
                                    # used to price a change the score would refuse
    extend_flexible_scenarios: bool = True
    extension_weeks: int = 52       # contingency window, used only when needed
    log: bool = False

    def __post_init__(self):
        if self.policy is None:
            # Default to the STRICTEST reading the evidence still permits, not
            # the most permissive one. `calibrate` shows two interpretations
            # survive the reference submission; solving against the permissive
            # one produces schedules the strict one rejects. The insurance costs
            # a few points of score, and a hard violation costs the whole run.
            self.policy = Policy(buffer_pushes_carriers_only=False)


@dataclass
class SolveOutcome:
    submission: Submission
    status: str
    objective: float
    best_bound: float
    wall_time: float
    schedule_end: int = 0


def _conflict_pairs(inst: Instance, net: Network, policy: Policy):
    """Pairs that may not share a week, precomputed once.

    Default reading (calibrated against the sample, see docs/SPEC.md section 8):
    only buffer-carrying work projects and is pushed; buffers bite on tunnel
    sectors; two activities sharing any location are provably on separate
    nights and so are exempt.
    """
    occ = {a: set(net.expand(a)) for a in inst.activities}
    ring = {a: set(net.buffer_locations(a, sorted(occ[a]))) for a in inst.activities}
    carries = {a for a in inst.activities if ring[a]}
    keep = (lambda s: s) if policy.buffer_bites_platforms \
        else (lambda s: {l for l in s if l.startswith("SEC:")})

    pairs = set()
    for a in inst.activities:
        if a not in carries:
            continue
        for b in inst.activities:
            if a == b:
                continue
            if policy.buffer_pushes_carriers_only and b not in carries:
                continue
            if policy.overlap_implies_separated and (occ[a] & occ[b]):
                continue
            if keep(ring[a]) & keep(occ[b]):
                pairs.add(tuple(sorted((a, b))))
    return sorted(pairs), occ


def solve(inst: Instance, cfg: SolverConfig) -> SolveOutcome:
    sc = cfg.scenario.upper()
    net = Network(inst)
    pairs, occ = _conflict_pairs(inst, net, cfg.policy)
    earliest = {a: inst.week_of(act.planned_start_date) for a, act in inst.activities.items()}
    # The supplied horizon is the initial planning view, not an arbitrary
    # stop-work date. A and C can trade delay against supply, so when work
    # cannot even fit in that view they get a controlled follow-on period.
    # B remains hard-bound by each planned completion date below.
    base_end = inst.horizon_weeks
    needs_extension = any(
        earliest[a] + act.total_accesses - 1 > base_end
        for a, act in inst.activities.items()
    )
    if sc in ("A", "C") and cfg.extend_flexible_scenarios and needs_extension:
        schedule_end = max(
            base_end,
            max(earliest[a] + act.total_accesses + cfg.extension_weeks
                for a, act in inst.activities.items()),
        )
    elif sc == "B":
        # Include later calendar weeks only to reach a still-hard deadline.
        schedule_end = max(base_end, max(
            (inst.week_of(c.planned_completion_date) for c in inst.contracts.values()),
            default=base_end,
        ))
    else:
        schedule_end = base_end
    weeks = list(range(1, schedule_end + 1))
    m = cp_model.CpModel()
    # A scheduled week completes on its Sunday.  A contract due on (say) a
    # Monday therefore cannot use that same week's access: it would finish six
    # days late.  Keep this in calendar days so the optimiser agrees exactly
    # with the independent validator.
    deadline = {}
    for a, act in inst.activities.items():
        due = inst.contracts[act.contract_number].planned_completion_date
        deadline[a] = max((w for w in weeks if inst.week_end(w) <= due), default=0)

    # --- window of legal weeks per activity ------------------------------
    win = {}
    for a, act in inst.activities.items():
        hi = deadline[a] if sc == "B" else schedule_end
        if cfg.protect_on_time_contracts and act.contract_number in cfg.protect_on_time_contracts:
            # A local improvement is never allowed to buy its benefit by
            # creating a new late contract elsewhere in the programme.
            hi = min(hi, deadline[a])
        win[a] = [w for w in weeks if earliest[a] <= w <= hi]
        if len(win[a]) < act.total_accesses and sc == "B":
            # B forbids overrun, so the activity must fit; ECLO is the only out
            win[a] = [w for w in weeks if earliest[a] <= w <= deadline[a]]

    x = {(a, w): m.NewBoolVar(f"x_{a}_{w}") for a in inst.activities for w in win[a]}
    if sc == "A":
        e = {}
    else:
        e = {(a, w): m.NewBoolVar(f"e_{a}_{w}") for a in inst.activities for w in win[a]}
        for k, v in e.items():
            m.Add(v <= x[k])

    # --- frozen work: the plan in force, which this re-plan may not disturb ---
    if cfg.freeze:
        for a, ws in cfg.freeze.items():
            if a not in inst.activities:
                continue
            for w in win[a]:
                m.Add(x[a, w] == (1 if w in ws else 0))

    # --- rule 1: workload conservation (2*units to keep it integral) ------
    for a, act in inst.activities.items():
        units = 2 * sum(x[a, w] for w in win[a])
        if e:
            units += sum(e[a, w] for w in win[a])
        m.Add(units >= 2 * act.total_accesses)

    # --- rule 3: precedence ----------------------------------------------
    for aid, act in inst.activities.items():
        p = act.predecessor_activity_id
        if not p or p not in inst.activities:
            continue
        for w in win[aid]:
            later = [x[p, w2] for w2 in win[p] if w2 >= w]
            if later:
                m.Add(sum(later) == 0).OnlyEnforceIf(x[aid, w])

    # --- rules 7 & 8: weekly allocation x workfronts ----------------------
    by_ct = collections.defaultdict(list)
    for aid, act in inst.activities.items():
        by_ct[(act.contract_number, act.activity_type)].append(aid)
    for (cn, _at), aids in by_ct.items():
        c = inst.contracts[cn]
        cap = c.max_access_per_week * c.number_of_workfronts
        for w in weeks:
            here = [x[a, w] for a in aids if (a, w) in x]
            if len(here) > cap:
                m.Add(sum(here) <= cap)

    # --- rules 4/5: possessions per location-week -------------------------
    at_loc = collections.defaultdict(list)
    for aid in inst.activities:
        for loc in occ[aid]:
            at_loc[loc].append(aid)

    excess_vars = []
    for loc, aids in at_loc.items():
        cap = inst.locations[loc].supply_capacity
        for w in weeks:
            here = [a for a in aids if (a, w) in x]
            if not here:
                continue
            n_pm, n_pc, n_c = [], [], []
            for a in here:
                t = inst.contracts[inst.activities[a].contract_number].access_type
                (n_pm if t == "PM" else n_pc if t == "PC" else n_c).append(x[a, w])
            poss = m.NewIntVar(0, len(here), f"p_{loc}_{w}")
            # PM alone; each PC holds one possession absorbing <=3 C; spare C in 4s
            m.Add(poss >= sum(n_pm) + sum(n_pc))
            m.Add(4 * poss >= 4 * sum(n_pm) + sum(n_pc) + sum(n_c))
            if sc == "A":
                m.Add(poss <= cap)
            elif sc == "C":
                ex = m.NewIntVar(0, 1, f"ex_{loc}_{w}")
                m.Add(poss <= cap + ex)
                excess_vars.append(ex)
            else:
                ex = m.NewIntVar(0, len(here), f"ex_{loc}_{w}")
                m.Add(poss <= cap + ex)
                excess_vars.append(ex)

    # --- rule 4: buffer conflicts ------------------------------------------
    for a, b in pairs:
        for w in weeks:
            if (a, w) in x and (b, w) in x:
                m.Add(x[a, w] + x[b, w] <= 1)

    # --- rule 9: ECLO continuity window, Scenario C only -------------------
    if sc == "C" and e:
        lines = sorted(inst.lines)
        start = {l: m.NewIntVar(1, schedule_end, f"eclo_start_{l}") for l in lines}
        act_lines = {a: {loc.split(":")[1] for loc in occ[a]} for a in inst.activities}
        for (a, w), var in e.items():
            for ln in act_lines[a]:
                m.Add(w >= start[ln]).OnlyEnforceIf(var)
                m.Add(w <= start[ln] + 1).OnlyEnforceIf(var)

    # --- objective ---------------------------------------------------------
    terms = []
    if sc in ("A", "C"):
        for a, act in inst.activities.items():
            c = inst.contracts[act.contract_number]
            late = [(w, max(0, (inst.week_end(w) - c.planned_completion_date).days))
                    for w in win[a]]
            late = [(w, days) for w, days in late if days]
            if not late:
                continue
            over = m.NewIntVar(0, 7 * schedule_end, f"over_{a}")
            for w, days in late:
                m.Add(over >= days).OnlyEnforceIf(x[a, w])
            wgt = int(round(CONTRACT_WEIGHT[c.contract_priority]
                            * (1 + ACTIVITY_NUDGE[act.activity_priority]) * SCALE))
            terms.append(wgt * over)
    if excess_vars:
        terms.append(7 * SCALE * sum(excess_vars))
    if e:
        terms.append(5 * SCALE * sum(e.values()))
    obj_expr = sum(terms) if terms else 0
    # A single lexicographic objective is substantially faster and safer than
    # solving twice for ordinary plan generation.  `tidy_weight` is larger
    # than every possible tie-break contribution, so one point of real score
    # can never be traded for fewer booked nights.
    tidy = sum(x.values()) + (sum(e.values()) if e else 0)
    ordinary_plan = not cfg.focus and not cfg.anchor
    tidy_weight = 2 * (len(x) + len(e)) + 1
    if ordinary_plan:
        m.Minimize(tidy_weight * obj_expr + tidy)
    if cfg.focus_first and cfg.focus and cfg.focus in win:
        # Earliest finish for the focus job first; the score then prices it.
        f_last = m.NewIntVar(0, schedule_end, "focus_first_last")
        for w in win[cfg.focus]:
            m.Add(f_last >= w).OnlyEnforceIf(x[cfg.focus, w])
        m.Minimize(1_000_000 * SCALE * f_last + obj_expr)
    elif not ordinary_plan:
        m.Minimize(obj_expr)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.max_seconds
    solver.parameters.num_search_workers = cfg.workers
    solver.parameters.random_seed = cfg.random_seed
    solver.parameters.log_search_progress = cfg.log
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveOutcome(Submission(), solver.StatusName(status), float("nan"),
                            float("nan"), solver.WallTime(), schedule_end)

    if ordinary_plan:
        chosen = {a: sorted(w for w in win[a] if solver.Value(x[a, w]))
                  for a in inst.activities}
        eclo = {(a, w) for (a, w) in e if solver.Value(e[a, w])} if e else set()
        sub = _build_submission(inst, net, chosen, eclo, sc)
        score = float(solver.Value(obj_expr)) / SCALE if terms else 0.0
        # A non-optimal run reports a conservative score bound; an optimal
        # run has the exact same value, as expected by the audit CLI.
        bound = score if status == cp_model.OPTIMAL else (
            float(solver.BestObjectiveBound()) / tidy_weight / SCALE)
        return SolveOutcome(sub, solver.StatusName(status), score, bound,
                            solver.WallTime(), schedule_end)

    # Phase 2: the workload rule is ">= total_accesses", so surplus nights are
    # free whenever they do not touch the objective -- the phase-1 answer books
    # far more track than the work needs.  Pin the objective at its proven value
    # and minimise nights booked.  Exact: it cannot trade away any real score.
    score1 = float(solver.Value(obj_expr)) if terms else 0.0
    bound1 = solver.BestObjectiveBound()
    t1 = solver.WallTime()
    if terms:
        m.Add(obj_expr <= int(round(score1)))
    # Preserve the valid phase-one assignment before reusing the CP-SAT
    # solver.  Reading variable values after an UNKNOWN second solve produces
    # arbitrary data, which used to create phantom overbookings on large runs.
    chosen1 = {a: sorted(w for w in win[a] if solver.Value(x[a, w]))
               for a in inst.activities}
    eclo1 = {(a, w) for (a, w) in e if solver.Value(e[a, w])} if e else set()
    if cfg.focus and cfg.focus in win:
        # Pull one job as early as the pinned objective allows, then settle the rest.
        last = m.NewIntVar(0, schedule_end, "focus_last")
        for w in win[cfg.focus]:
            m.Add(last >= w).OnlyEnforceIf(x[cfg.focus, w])
        churn = []
        if cfg.anchor:
            for (a, w), var in x.items():
                if a == cfg.focus:
                    continue
                churn.append((1 - var) if w in cfg.anchor.get(a, ()) else var)
        m.Minimize(10000 * last + (100 * sum(churn) if churn else 0) + tidy)
    elif cfg.anchor:
        # Re-planning: among all equally-good schedules, pick the one that moves
        # the least existing work. Exact -- the objective is already pinned, so
        # churn is minimised without trading away any score.
        churn = []
        for (a, w), var in x.items():
            was = w in cfg.anchor.get(a, ())
            churn.append((1 - var) if was else var)
        m.Minimize(100 * sum(churn) + tidy)
    else:
        m.Minimize(tidy)
    status2 = solver.Solve(m)
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        status = status2
        chosen = {a: sorted(w for w in win[a] if solver.Value(x[a, w]))
                  for a in inst.activities}
        eclo = {(a, w) for (a, w) in e if solver.Value(e[a, w])} if e else set()
    else:
        chosen, eclo = chosen1, eclo1
    sub = _build_submission(inst, net, chosen, eclo, sc)
    return SolveOutcome(sub, solver.StatusName(status), score1 / SCALE,
                        bound1 / SCALE, t1 + solver.WallTime(), schedule_end)


def _build_submission(inst, net, chosen, eclo, scenario) -> Submission:
    """Fill in access_night indices and co_share_group labels after the solve."""
    accesses, occupancies = [], []

    # access_night: bin the week's activities of a (contract, type) into the
    # contract's granted nights, at most `workfronts` per night.
    night_of = {}
    per = collections.defaultdict(list)
    for aid, ws in chosen.items():
        act = inst.activities[aid]
        for w in ws:
            per[(act.contract_number, act.activity_type, w)].append(aid)
    for (cn, _at, w), aids in per.items():
        c = inst.contracts[cn]
        load = [0] * (c.max_access_per_week + 1)
        for aid in sorted(aids):
            slot = min(range(1, c.max_access_per_week + 1), key=lambda n: load[n])
            load[slot] += 1
            night_of[(aid, w)] = slot

    for aid, ws in sorted(chosen.items()):
        for seq, w in enumerate(ws, start=1):
            accesses.append(Access(aid, seq, w, (aid, w) in eclo, night_of[(aid, w)]))

    # co_share_group: pack each location-week into legal possessions.
    at_lw = collections.defaultdict(list)
    for aid, ws in chosen.items():
        for w in ws:
            for loc in net.expand(aid):
                at_lw[(loc, w)].append(aid)
    # An access type outside PM/PC/C would fall through every bucket below and
    # silently leave the activity out of the occupancy plan -- a submission that
    # looks optimal and is not. Refuse to build one.
    known = {"PM", "PC", "C"}
    bad = sorted({c.access_type for c in inst.contracts.values()
                  if c.access_type not in known})
    if bad:
        offenders = sorted(cn for cn, c in inst.contracts.items()
                           if c.access_type in bad)
        raise ValueError(
            f"unknown access_type(s) {bad} on {offenders} in "
            f"07_PROJECT_DETAILS.csv; only {sorted(known)} are defined")

    for (loc, w), aids in at_lw.items():
        typ = lambda a: inst.contracts[inst.activities[a].contract_number].access_type
        pm = sorted(a for a in aids if typ(a) == "PM")
        pc = sorted(a for a in aids if typ(a) == "PC")
        co = sorted(a for a in aids if typ(a) == "C")
        groups: list[list[str]] = [[a] for a in pm]
        for host in pc:
            groups.append([host] + co[:3])
            co = co[3:]
        for i in range(0, len(co), 4):
            groups.append(co[i:i + 4])
        for idx, members in enumerate(groups, start=1):
            for a in members:
                occupancies.append(Occupancy(a, w, loc, f"b{idx}"))

    last = collections.defaultdict(int)
    for aid, ws in chosen.items():
        if ws:
            cn = inst.activities[aid].contract_number
            last[cn] = max(last[cn], max(ws))
    results = []
    for cn, c in inst.contracts.items():
        sim = inst.week_end(last[cn]) if last[cn] else c.planned_completion_date
        results.append(Result(scenario, cn, sim,
                              max(0, (sim - c.planned_completion_date).days)))
    return Submission(accesses, occupancies, results)
