"""Read-only operational facts from a validated Trackspace schedule/report.

Counts are not proofs that a different schedule is feasible or impossible.
"""
from collections import defaultdict


def schedule_summary(inst, sub, report=None):
    groups = defaultdict(set)
    for row in sub.occupancies:
        groups[row.week, row.location_id].add(row.co_share_group)
    utilization = [{"week": w, "location_id": loc, "used": len(gs),
                    "capacity": inst.locations[loc].supply_capacity,
                    "excess": max(0, len(gs)-inst.locations[loc].supply_capacity)}
                   for (w, loc), gs in sorted(groups.items())]
    results = [{"contract_number": r.contract_number,
                "overrun_days": r.overrun_days,
                "simulated_completion_date": str(r.simulated_completion_date)}
               for r in sub.results]
    if report is not None:
        utilization = report.get("utilization", [])
        results = report.get("results", [])
    eclo = [a for a in sub.accesses if a.eclo]
    by_contract = defaultdict(list)
    for a in eclo:
        by_contract[inst.activities[a.activity_id].contract_number].append(a.week)
    return {"source": "Trackspace selected schedule", "is_preview": True,
            "score": report.get("score") if report else None,
            "feasible": report.get("feasible") if report else None,
            "hard_violations": report.get("hard_violations", []) if report else None,
            "eclo_accesses": report.get("eclo_nights_total", len(eclo)) if report else len(eclo),
            "eclo_weeks": sorted({a.week for a in eclo}),
            "eclo_by_contract": [{"who":inst.contracts[cn].contract_description,
                                  "worst":len(ws), "weeks":sorted(set(ws)),
                                  "unit":" ECLO accesses"} for cn, ws in sorted(by_contract.items())],
            "extra_access_nights": sum(r["excess"] for r in utilization),
            "overrun_days": sum(r.get("overrun_days") or 0 for r in results),
            "contracts_overrunning": sum((r.get("overrun_days") or 0)>0 for r in results),
            "utilization": utilization, "results": results,
            "counting_note": "ECLO counts activity-access rows once, not each location they cover. "
            "Extra access counts possessions above nominal supply per location-week. "
            "Full nominal capacity does not prove no slack or that a change is impossible."}


def attention_items(inst, sub, report):
    facts = schedule_summary(inst, sub, report)
    items = []
    for r in facts['results']:
        if (r.get('overrun_days') or 0)>0:
            cn = r['contract_number']
            items.append({"severity":"act",
                          "title":f"{inst.contracts[cn].contract_description}: {r['overrun_days']} days late in this plan",
                          "detail":f"Scheduled finish: {r['simulated_completion_date']}. Earlier completion has not been tested.",
                          "action":"Review the deadline or rerun Trackspace with revised inputs."})
    weeks = defaultdict(list)
    for r in facts['utilization']:
        if r['used'] >= r['capacity']:
            weeks[r['week']].append(r)
    for w, rows in sorted(weeks.items(), key=lambda pair:(-len(pair[1]),pair[0])):
        items.append({"severity":"watch", "week":w,
                      "title":f"Week {w}: {len(rows)} worksites at or above nominal capacity",
                      "detail":f"{inst.week_start(w):%d %b} – {inst.week_end(w):%d %b}. Confirm access arrangements; this is not a test of rescheduling options.",
                      "action":"Confirm crews, shared access and any purchased capacity.",
                      "locations":[r['location_id'] for r in rows]})
    if not items:
        items.append({"severity":"ok", "title":"No lateness or nominal-capacity alerts",
                      "detail":"This describes the selected plan, not a guarantee about new requests.","action":""})
    return items


def requested_changes(conflict, requested, planned):
    changes = []
    for aid in conflict.parties:
        before, after = requested.get(aid, []), planned.get(aid, [])
        if before != after:
            changes.append(f"{aid}: weeks {', '.join(map(str,before))} → {', '.join(map(str,after))}")
    return '; '.join(changes) or "Requested weeks retained. Review the selected plan's shared access, ECLO and extra access; the schedule passed the bundled validator."
