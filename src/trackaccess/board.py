"""Operational views: what a works controller actually needs to see.

The solver thinks in activities and weeks. A controller thinks in "who is on
this piece of track this week, who are they sharing with, and what is closed
around them". This module translates.
"""
from __future__ import annotations

import collections

from .model import Instance
from .network import Network
from .submission import Submission
from .validate import Policy


def week_board(inst: Instance, sub: Submission, week: int) -> list[dict]:
    """Every location worked in this week, one row per possession."""
    net = Network(inst)
    members = collections.defaultdict(set)
    for o in sub.occupancies:
        if o.week == week:
            members[(o.location_id, o.co_share_group)].add(o.activity_id)

    eclo = {(a.activity_id, a.week) for a in sub.accesses if a.eclo}
    rows = []
    for (loc, grp), aids in sorted(members.items()):
        crew = []
        for a in sorted(aids):
            act = inst.activities[a]
            c = inst.contracts[act.contract_number]
            crew.append({
                "activity": a, "contract": act.contract_number,
                "who": c.contract_description, "access_type": c.access_type,
                "nature": c.nature_of_activity, "priority": c.contract_priority,
                "eclo": (a, week) in eclo,
            })
        rows.append({
            "location": loc,
            "kind": "Platform" if loc.startswith("PLAT:") else "Tunnel",
            "line": loc.split(":")[1], "bound": loc.split(":")[-1],
            "possession": grp,
            "capacity": inst.locations[loc].supply_capacity,
            "team_count": len(crew),
            "sharing": len(crew) > 1,
            "eclo": any(c["eclo"] for c in crew),
            "crew": crew,
        })
    return rows


def closures_for_week(inst: Instance, sub: Submission, week: int,
                      policy: Policy = Policy(), footprints=None) -> list[dict]:
    """Locations kept clear by somebody's safety buffer this week."""
    net = Network(inst)
    working = {o.activity_id for o in sub.occupancies if o.week == week}
    keep = (lambda s: s) if policy.buffer_bites_platforms \
        else (lambda s: {l for l in s if l.startswith("SEC:")})
    out = []
    for aid in sorted(working):
        if footprints is not None:
            fp = footprints.get(aid, {})
            occ = set(fp.get('workLocations', []))
            ring = set(fp.get('exclusion', []))
        else:
            occ = set(net.expand(aid))
            ring = keep(set(net.buffer_locations(aid, sorted(occ))))
        if not ring:
            continue
        c = inst.contracts[inst.activities[aid].contract_number]
        out.append({"activity": aid, "contract": c.contract_number,
                    "nature": c.nature_of_activity,
                    "closed": sorted(ring - occ)})
    return out


def contract_rows(inst: Instance, sub: Submission) -> list[dict]:
    """One row per contract: what it is, when it runs, whether it lands."""
    weeks = collections.defaultdict(list)
    for a in sub.accesses:
        weeks[inst.activities[a.activity_id].contract_number].append(a.week)
    rows = []
    for cn, c in sorted(inst.contracts.items()):
        ws = sorted(weeks.get(cn, []))
        if not ws:
            continue
        last = max(ws)
        sim = inst.week_end(last)
        over = max(0, (sim - c.planned_completion_date).days)
        due_week = inst.week_of(c.planned_completion_date)
        # Work completes on Sunday, so a Monday--Saturday deadline rules out
        # the week containing it.  This matches solver and validator timing.
        if inst.week_end(due_week) > c.planned_completion_date:
            due_week -= 1
        rows.append({
            "contract": cn, "who": c.contract_description,
            "priority": c.contract_priority, "nature": c.nature_of_activity,
            "access_type": c.access_type,
            "nights": len(ws), "first_week": min(ws), "last_week": last,
            "deadline_week": due_week,
            "finishes": sim, "due": c.planned_completion_date,
            "overrun_days": over,
            "status": "Late" if over else "On time",
        })
    return rows


def headline(inst: Instance, facts) -> str:
    """One sentence a controller can read and act on."""
    n_late = len(facts.contracts_overrunning)
    total = len(inst.contracts)
    if n_late == 0:
        return (f"All {len(inst.activities)} jobs scheduled. "
                f"Every one of the {total} contracts finishes on time.")
    stuck = sum(1 for a in facts.activities
                if a.structural_days and a.structural_days == a.overrun_days)
    bit = (f" {stuck} of them cannot be saved — the work needs more nights than "
           f"the calendar allows." if stuck else "")
    return (f"All {len(inst.activities)} jobs scheduled. "
            f"{n_late} of {total} contracts finish late.{bit}")


def crew_order(inst: Instance, sub: Submission, contract: str, footprints=None) -> dict:
    """One contractor's working orders: every week they are out, where, and who
    with. This is the sheet a team actually carries."""
    from .network import Network
    net = Network(inst)
    mine = {a for a, act in inst.activities.items() if act.contract_number == contract}
    weeks = collections.defaultdict(set)
    for a in sub.accesses:
        if a.activity_id in mine:
            weeks[a.week].add(a.activity_id)

    group_of, at_loc = {}, collections.defaultdict(set)
    for o in sub.occupancies:
        group_of[(o.activity_id, o.week, o.location_id)] = o.co_share_group
        at_loc[(o.location_id, o.week, o.co_share_group)].add(o.activity_id)

    eclo = {(a.activity_id, a.week) for a in sub.accesses if a.eclo}
    c = inst.contracts[contract]
    nights = []
    for wk in sorted(weeks):
        sites = []
        for aid in sorted(weeks[wk]):
            if footprints is not None:
                locs = sorted({o.location_id for o in sub.occupancies if o.activity_id == aid and o.week == wk})
                ring = sorted(set(footprints.get(aid, {}).get('exclusion', []))-set(locs))
            else:
                locs = sorted(net.expand(aid))
                ring = sorted(set(net.buffer_locations(aid, locs)) - set(locs))
            others = set()
            for loc in locs:
                g = group_of.get((aid, wk, loc))
                if g:
                    others |= {x for x in at_loc[(loc, wk, g)] if x not in mine}
            sites.append({
                "activity": aid,
                "from": inst.activities[aid].start_location_id,
                "to": inst.activities[aid].end_location_id,
                "locations": locs,
                "sharing_with": sorted(
                    {inst.activities[o].contract_number for o in others}),
                "must_keep_clear": ring,
                "eclo": (aid, wk) in eclo,
            })
        nights.append({"week": wk,
                       "from": inst.week_start(wk), "to": inst.week_end(wk),
                       "jobs": sites})
    return {"contract": contract, "description": c.contract_description,
            "nature": c.nature_of_activity, "access_type": c.access_type,
            "weekly_allowance": c.max_access_per_week,
            "teams": c.number_of_workfronts,
            "due": c.planned_completion_date, "weeks": nights}


def recommend(summaries: dict) -> tuple[str, list[str]]:
    """Pick a plan to put forward, and say why in terms a planner can argue with.

    The rule, in order: land the most contracts on time; break ties by causing
    the least disruption to passengers (early closures), then by asking for the
    fewest extra access-nights. Stated plainly so a planner can disagree with the
    rule rather than with an unexplained answer.
    """
    live = {k: v for k, v in summaries.items() if v}
    if not live:
        return "", ["No plan could be built."]
    best = max(live, key=lambda k: (live[k]["on_time"],
                                    -live[k]["eclo"], -live[k]["extra"]))
    s = live[best]
    why = []
    others = {k: v for k, v in live.items() if k != best}

    # why[0] is a clause the caller can put after the plan name, no markdown.
    if s["on_time"] == s["total"]:
        why.append(f"It is the only plan that lands every one of the {s['total']} "
                   f"contracts on time."
                   if all(v["on_time"] < v["total"] for v in others.values())
                   else f"It lands all {s['total']} contracts on time.")
    else:
        beaten = [k for k, v in others.items() if v["on_time"] < s["on_time"]]
        why.append(f"It gets {s['on_time']} of {s['total']} contracts in on time"
                   + (" — more than "
                      + " or ".join(f"{k} ({others[k]['on_time']})" for k in beaten)
                      if beaten else "") + ".")

    costs = []
    if s["eclo"]:
        costs.append(f"{s['eclo']} night(s) closing early or opening late, which "
                     f"commuters feel")
    if s["extra"]:
        costs.append(f"{s['extra']} access-night(s) above the nominal allowance, "
                     f"which have to be negotiated")
    if s["worst"]:
        costs.append(f"a worst-case slip of {s['worst']} days")
    why.append("What it costs: " + ("; ".join(costs) if costs else
                                    "nothing — no early closures, no extra nights, "
                                    "no slipped deadlines."))

    for k, v in others.items():
        diff_bits = []
        if v["on_time"] != s["on_time"]:
            diff_bits.append(f"{v['on_time']} of {v['total']} on time")
        if v["eclo"] != s["eclo"]:
            diff_bits.append(f"{v['eclo']} early closures")
        if v["worst"] != s["worst"]:
            diff_bits.append(f"worst slip {v['worst']} days")
        if diff_bits:
            why.append(f"*{k}* instead gives " + ", ".join(diff_bits) + ".")

    why.append("Choose differently if your priorities differ — nothing here is "
               "locked in, and every plan passes the same safety checks.")
    return best, why


def needs_attention(inst: Instance, sub: Submission, facts) -> list[dict]:
    """What is genuinely open on this schedule, hardest thing first.

    Deliberately NOT the clashes: those were settled when the schedule was built,
    and presenting them as outstanding would misrepresent the state of the plan.
    What is open is late work someone could still act on, late work nobody can,
    and the weeks where the network has no slack left.
    """
    items = []

    avoidable, stuck = [], []
    for a in facts.activities:
        if not a.overrun_days:
            continue
        (stuck if a.structural_days == a.overrun_days else avoidable).append(a)

    for a in sorted(avoidable, key=lambda a: (-a.contract_priority, -a.overrun_days)):
        c = inst.contracts[a.contract_number]
        tier = {1: "P1 critical", 2: "P2 important", 3: "P3 routine"}[a.contract_priority]
        from . import names as N
        items.append({
            "severity": "act",
            "title": f"{c.contract_description} finishes {a.overrun_days} days late — "
                     f"it could run earlier, but only by moving other work",
            "detail": f"Their job on the {N.place(inst.activities[a.activity_id].start_location_id)} "
                      f"({a.activity_id}, {tier}) needs {a.nights_required} night(s) and "
                      f"could finish by week {a.floor_week}. The schedule keeps it at "
                      f"week {a.last_week} because every earlier week has other work in "
                      f"the way. Deadline is week {a.deadline_week}.",
            "action": f"Ask for the swap that brings it forward, see what it costs, "
                      f"then decide.",
            "job": a.activity_id, "floor": a.floor_week, "last": a.last_week,
        })

    if stuck:
        from . import names as N
        names = ", ".join(sorted({inst.contracts[a.contract_number].contract_description
                                  for a in stuck}))
        worst = max(a.overrun_days for a in stuck)
        jobs = []
        for a in stuck:
            act = inst.activities[a.activity_id]
            c = inst.contracts[a.contract_number]
            dl = a.deadline_week
            jobs.append({
                "job": a.activity_id, "contractor": c.contract_description,
                "where": N.place(act.start_location_id),
                "nights": a.nights_required, "earliest": a.earliest_start_week,
                "floor": a.floor_week, "floor_date": f"{inst.week_end(a.floor_week):%d %b %Y}",
                "deadline": dl, "over": a.structural_days,
                "fits": max(0, dl - a.earliest_start_week + 1),
            })
        items.append({
            "severity": "known", "jobs": jobs,
            "title": f"{len(stuck)} job(s) cannot finish on time whatever is done "
                     f"({names})",
            "detail": f"They need more nights than the calendar allows before their "
                      f"deadline. Nothing in the schedule fixes that; worst is {worst} days.",
            "action": "Renegotiate the dates with the contractor. Do not re-plan around it.",
        })

    # weeks with no slack left: every location at or over its weekly limit
    tight = collections.Counter()
    groups = collections.defaultdict(set)
    for o in sub.occupancies:
        groups[(o.location_id, o.week)].add(o.co_share_group)
    for (loc, wk), gs in groups.items():
        if len(gs) >= inst.locations[loc].supply_capacity:
            tight[wk] += 1
    for wk, n in tight.most_common(2):
        if n < 3:
            break
        items.append({
            "severity": "watch", "week": wk,
            "title": f"Week {wk} has no slack — {n} worksites at their weekly limit",
            "detail": f"{inst.week_start(wk):%d %b} – {inst.week_end(wk):%d %b}. "
                      f"If anything slips that week there is nowhere for it to go.",
            "action": "Confirm crews and access with contractors the week before.",
        })

    if not items:
        items.append({"severity": "ok", "title": "Nothing needs a decision",
                      "detail": "Every contract lands on time and no week is at its "
                                "limit.", "action": ""})
    return items
