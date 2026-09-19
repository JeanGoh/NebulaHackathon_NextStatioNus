"""Why the schedule looks the way it does.

Two layers, deliberately separated:

1. A deterministic analyser that extracts *facts* from a solved schedule --
   which activity forced a contract late, whether that lateness was structural
   or caused by contention, and exactly what blocks an activity from an earlier
   week. No model involved; these are checks against the instance.

2. An optional LLM layer that turns those facts into prose for a works
   controller. It is handed the facts and may not invent others. With no API
   key the app still shows every fact, just without the narration.

The ordering matters: the language model explains a decision it did not make.
"""
from __future__ import annotations

import collections
import json
import os
from dataclasses import asdict, dataclass, field

from .model import Instance
from .network import Network
from .submission import Submission
from .validate import Policy


@dataclass
class ActivityFacts:
    activity_id: str
    contract_number: str
    contract_priority: int
    nights_required: int
    earliest_start_week: int
    floor_week: int              # earliest finish ignoring all contention
    scheduled_weeks: list[int]
    last_week: int
    deadline_week: int
    overrun_days: int
    structural_days: int         # unavoidable: floor already past the deadline
    contention_days: int         # the part contention added
    blocked_weeks: dict = field(default_factory=dict)


@dataclass
class ScheduleFacts:
    scenario: str
    objective_score: float
    overrun_days_total: int
    eclo_nights: int
    excess_nights: int
    contracts_overrunning: list[str]
    structural_overrun_days: int
    contention_overrun_days: int
    activities: list[ActivityFacts]
    hotspots: list[dict]
    co_sharing: dict

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


def _floor_week(inst: Instance, aid: str, eclo_cap: int) -> int:
    """Earliest week this activity could finish if it had the railway to itself."""
    act = inst.activities[aid]
    sw = inst.week_of(act.planned_start_date)
    p = act.predecessor_activity_id
    if p and p in inst.activities:
        sw = max(sw, _floor_week(inst, p, eclo_cap) + 1)
    n = act.total_accesses
    for w in range(1, 40):
        if w + 0.5 * min(w, eclo_cap) >= n - 1e-9:
            return sw + w - 1
    return sw + n - 1


def why_not_week(inst: Instance, sub: Submission, aid: str, week: int,
                 policy: Policy = Policy()) -> list[str]:
    """What stops this activity from taking that week? Checked, not guessed."""
    net = Network(inst)
    act = inst.activities[aid]
    reasons: list[str] = []

    if week < inst.week_of(act.planned_start_date):
        reasons.append(
            f"week {week} is before {aid}'s planned start "
            f"({act.planned_start_date.isoformat()}, week "
            f"{inst.week_of(act.planned_start_date)})")

    p = act.predecessor_activity_id
    if p:
        pw = [a.week for a in sub.accesses if a.activity_id == p]
        if pw and week <= max(pw):
            reasons.append(f"{aid} must follow {p}, which runs to week {max(pw)}")

    occ_by_week = collections.defaultdict(lambda: collections.defaultdict(set))
    for o in sub.occupancies:
        occ_by_week[o.week][o.location_id].add(o.activity_id)

    mine = set(net.expand(aid))
    for loc in sorted(mine):
        others = occ_by_week[week].get(loc, set()) - {aid}
        if not others:
            continue
        cap = inst.locations[loc].supply_capacity
        groups = {o.co_share_group for o in sub.occupancies
                  if o.week == week and o.location_id == loc}
        if len(groups) >= cap:
            reasons.append(
                f"{loc} is at capacity in week {week} "
                f"({len(groups)}/{cap} possessions, held by "
                f"{', '.join(sorted(others)[:3])})")

    ring = set(net.buffer_locations(aid, sorted(mine)))
    keep = (lambda s: s) if policy.buffer_bites_platforms \
        else (lambda s: {l for l in s if l.startswith("SEC:")})
    present = {a for locs in occ_by_week[week].values() for a in locs} - {aid}
    for b in sorted(present):
        if b not in inst.activities:
            continue
        b_occ = set(net.expand(b))
        if policy.overlap_implies_separated and (mine & b_occ):
            continue
        clash = keep(ring) & keep(b_occ)
        if clash:
            reasons.append(
                f"safety buffer around {aid} would close "
                f"{sorted(clash)[0]} in week {week}, where {b} is working")

    c = inst.contracts[act.contract_number]
    same = {a.activity_id for a in sub.accesses
            if a.week == week
            and a.activity_id in inst.activities
            and inst.activities[a.activity_id].contract_number == act.contract_number
            and inst.activities[a.activity_id].activity_type == act.activity_type} - {aid}
    if len(same) >= c.max_access_per_week * c.number_of_workfronts:
        reasons.append(
            f"{act.contract_number} already runs {len(same)} activities in week "
            f"{week}, its weekly limit "
            f"({c.max_access_per_week} nights x {c.number_of_workfronts} workfronts)")

    return reasons or [f"nothing blocks week {week} -- the solver had no reason to use it"]


def analyse(inst: Instance, sub: Submission, scenario: str,
            objective: float = float("nan"), policy: Policy = Policy()) -> ScheduleFacts:
    eclo_cap = {"A": 0, "C": 2, "B": 99}[scenario.upper()]
    weeks_of = collections.defaultdict(list)
    for a in sub.accesses:
        # A submission may belong to a previously uploaded programme.  The
        # validator reports that mismatch; the explanatory UI must not crash.
        if a.activity_id in inst.activities:
            weeks_of[a.activity_id].append(a.week)

    acts, structural, contention = [], 0, 0
    for aid, act in sorted(inst.activities.items()):
        ws = sorted(weeks_of.get(aid, []))
        if not ws:
            continue
        c = inst.contracts[act.contract_number]
        dl = inst.week_of(c.planned_completion_date)
        if inst.week_end(dl) > c.planned_completion_date:
            dl -= 1
        floor = _floor_week(inst, aid, eclo_cap)
        over = max(0, (inst.week_end(ws[-1]) - c.planned_completion_date).days)
        struct = max(0, (inst.week_end(floor) - c.planned_completion_date).days)
        struct = min(struct, over)
        structural += struct
        contention += over - struct
        blocked = {}
        if over > struct:
            for w in range(max(floor, dl), ws[-1]):
                if w not in ws:
                    blocked[w] = why_not_week(inst, sub, aid, w, policy)
                if len(blocked) >= 3:
                    break
        acts.append(ActivityFacts(
            aid, act.contract_number, c.contract_priority, act.total_accesses,
            inst.week_of(act.planned_start_date), floor, ws, ws[-1], dl,
            over, struct, over - struct, blocked))

    groups = collections.defaultdict(set)
    for o in sub.occupancies:
        groups[(o.location_id, o.week)].add(o.co_share_group)
    hotspots = []
    for (loc, wk), gs in groups.items():
        cap = inst.locations[loc].supply_capacity
        if len(gs) >= cap:
            who = sorted({o.activity_id for o in sub.occupancies
                          if o.location_id == loc and o.week == wk})
            hotspots.append({"location": loc, "week": wk, "possessions": len(gs),
                             "capacity": cap, "activities": who})
    hotspots.sort(key=lambda h: (-h["possessions"] / h["capacity"], h["location"]))

    members = collections.defaultdict(set)
    for o in sub.occupancies:
        members[(o.location_id, o.week, o.co_share_group)].add(o.activity_id)
    sizes = collections.Counter(len(v) for v in members.values())
    shared = sum(n for k, n in sizes.items() if k > 1)

    last = collections.defaultdict(int)
    for aid, ws in weeks_of.items():
        last[inst.activities[aid].contract_number] = max(
            last[inst.activities[aid].contract_number], max(ws))
    overrunning = sorted(cn for cn, c in inst.contracts.items()
                         if last.get(cn) and inst.week_end(last[cn]) > c.planned_completion_date)

    return ScheduleFacts(
        scenario=scenario.upper(), objective_score=objective,
        overrun_days_total=sum(a.overrun_days for a in acts),
        eclo_nights=sum(1 for a in sub.accesses if a.eclo),
        excess_nights=sum(max(0, len(gs) - inst.locations[loc].supply_capacity)
                          for (loc, _w), gs in groups.items()),
        contracts_overrunning=overrunning,
        structural_overrun_days=structural, contention_overrun_days=contention,
        activities=acts, hotspots=hotspots[:15],
        co_sharing={"possessions_total": len(members),
                    "possessions_shared": shared,
                    "largest_possession": max(sizes) if sizes else 0,
                    "distribution": dict(sorted(sizes.items()))},
    )


# --------------------------------------------------------------------------
# Optional LLM narration. Facts in, prose out; it may not invent anything.
# --------------------------------------------------------------------------

SYSTEM = """You brief rail works controllers on overnight track access plans.

You are given FACTS extracted from a schedule that a constraint solver has
already produced and a validator has already checked. Explain them.

Rules:
- Use only the facts given. Never invent an activity, week, location or number.
- If the facts do not answer the question, say so plainly and say what would.
- A works controller is reading this at 2am. Lead with the answer.
- Distinguish structural overrun (unavoidable given start dates and nights
  required) from contention overrun (caused by competing demand). This
  distinction is the single most useful thing you can convey.
- Be concise. No preamble, no restating the question, no bullet lists longer
  than four items.
- Plain English. "The tunnel between the two hubs" beats "SEC:BET:H01_H02:EB",
  though you may give the code in brackets once."""


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def narrate(facts: ScheduleFacts, question: str | None = None,
            model: str = "claude-sonnet-4-5", max_tokens: int = 900) -> str:
    """Ask a model to explain the facts. Raises if no key is configured."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("pip install anthropic to enable narration") from exc
    if not llm_available():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    ask = question or (
        "Write a short handover brief on this schedule: what it delivers, which "
        "contracts finish late and why, and where the network is tightest.")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=max_tokens, system=SYSTEM,
        messages=[{"role": "user",
                   "content": f"FACTS:\n{facts.to_json()}\n\nQUESTION: {ask}"}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
