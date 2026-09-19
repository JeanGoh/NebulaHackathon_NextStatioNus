"""Command line surface: python3 -m trackaccess <command>"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .model import load_instance
from .network import Network
from .submission import load_submission, save_submission
from .validate import Policy, validate


def _policy(ns) -> Policy:
    return Policy(
        buffer_bites_platforms=ns.buffer_bites_platforms,
        buffer_pushes_carriers_only=not ns.buffer_pushes_all,
        overlap_implies_separated=not ns.no_overlap_exemption,
        overrun_basis=ns.overrun_basis,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trackaccess")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="check a submission against an instance")
    v.add_argument("--instance", required=True)
    v.add_argument("--submission", required=True)
    v.add_argument("--scenario", choices=["A", "B", "C"])
    v.add_argument("--json", action="store_true", help="emit the raw report")
    v.add_argument("--strict", action="store_true",
                   help="use the strictest plausible buffer reading (insurance check)")
    v.add_argument("--buffer-excludes-platforms", action="store_true")
    v.add_argument("--buffer-pushes-all", action="store_true")
    v.add_argument("--no-overlap-exemption", action="store_true")
    v.add_argument("--overrun-basis", choices=["activity", "contract"],
                   default="activity",
                   help="how priority_weighted_score measures an activity's overrun")

    s = sub.add_parser("solve", help="produce a submission for one or all scenarios")
    s.add_argument("--instance", required=True)
    s.add_argument("--out", required=True, help="directory; one subfolder per scenario")
    s.add_argument("--scenario", choices=["A", "B", "C", "all"], default="all")
    s.add_argument("--seconds", type=float, default=60.0)
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--optimistic-buffers", action="store_true",
                   help="assume the most permissive surviving rule reading; "
                        "scores better but may be judged infeasible")

    cal = sub.add_parser("calibrate",
                         help="infer ambiguous rule semantics from a known-good submission")
    cal.add_argument("--instance", required=True)
    cal.add_argument("--reference", required=True,
                     help="a submission the organisers state is feasible")
    cal.add_argument("--scenario", choices=["A", "B", "C"])

    e = sub.add_parser("expand", help="print the locations an activity books")
    e.add_argument("--instance", required=True)
    e.add_argument("--activity")
    e.add_argument("--out", help="write activity_id,location_id as CSV")

    ns = ap.parse_args(argv)

    if ns.cmd == "solve":
        from pathlib import Path as _P
        from .solve import SolverConfig, solve as _solve
        inst = load_instance(ns.instance)
        scenarios = ["A", "B", "C"] if ns.scenario == "all" else [ns.scenario]
        rc = 0
        for sc in scenarios:
            from .validate import Policy as _Pol
            pol = _Pol(buffer_pushes_carriers_only=True) if ns.optimistic_buffers else None
            out = _solve(inst, SolverConfig(scenario=sc, max_seconds=ns.seconds,
                                            workers=ns.workers, policy=pol))
            if not out.submission.accesses:
                print(f"Scenario {sc}: {out.status} -- no schedule produced"); rc = 1; continue
            dest = _P(ns.out) / sc
            save_submission(out.submission, dest)
            rep = validate(inst, out.submission, sc)
            gap = "" if out.objective == out.best_bound else f" (bound {out.best_bound:.1f})"
            print(f"Scenario {sc}: {out.status} score={out.objective:.1f}{gap} "
                  f"in {out.wall_time:.2f}s -> {dest}")
            print(f"  independent check: "
                  f"{'FEASIBLE' if rep.feasible else 'INFEASIBLE'} "
                  f"({len(rep.hard_violations)} violations), "
                  f"validator score={rep.soft_scores.get('objective_score', 'n/a')}")
            if not rep.feasible:
                rc = 1
                for v in rep.hard_violations[:5]:
                    print(f"    [{v.rule}] {v.detail}")
        return rc

    if ns.cmd == "calibrate":
        from .calibrate import calibrate as _cal
        inst = load_instance(ns.instance)
        ref = load_submission(ns.reference)
        print(_cal(inst, ref, ns.scenario).summary())
        return 0

    if ns.cmd == "expand":
        inst = load_instance(ns.instance)
        net = Network(inst)
        ids = [ns.activity] if ns.activity else sorted(inst.activities)
        rows = [(a, loc) for a in ids for loc in net.expand(a)]
        if ns.out:
            with open(ns.out, "w", newline="") as fh:
                w = csv.writer(fh); w.writerow(["activity_id", "location_id"]); w.writerows(rows)
            print(f"{len(rows)} rows -> {ns.out}")
        else:
            for a, loc in rows:
                print(f"{a}\t{loc}")
        return 0

    inst = load_instance(ns.instance)
    submission = load_submission(ns.submission)
    pol = Policy(buffer_bites_platforms=False, buffer_pushes_carriers_only=False,
                 overlap_implies_separated=False,
                 overrun_basis=ns.overrun_basis) if ns.strict else _policy(ns)
    rep = validate(inst, submission, ns.scenario, pol)

    if ns.json:
        print(json.dumps(rep.as_dict(), indent=2))
    else:
        mark = "FEASIBLE" if rep.feasible else "INFEASIBLE"
        print(f"Scenario {rep.scenario}: {mark}  ({len(rep.hard_violations)} hard violations)")
        for viol in rep.hard_violations[:25]:
            print(f"  [{viol.rule}] {viol.detail}")
        if len(rep.hard_violations) > 25:
            print(f"  ... and {len(rep.hard_violations) - 25} more")
        s = rep.soft_scores
        print(f"  overrun_days={s['overrun_days_total']} "
              f"excess_nights={s['excess_access_nights_total']} "
              f"eclo={s['eclo_nights_total']} "
              f"weighted={s['priority_weighted_score']}")
        if "objective_score" in s:
            print(f"  OBJECTIVE SCORE = {s['objective_score']}   (lower is better)")
    return 0 if rep.feasible else 1


if __name__ == "__main__":
    sys.exit(main())
