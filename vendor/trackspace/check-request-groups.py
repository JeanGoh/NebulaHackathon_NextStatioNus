"""Exact weekly assignment check for otherwise locally consistent requests."""
import json
import sys
from ortools.sat.python import cp_model


def check(weeks):
    results = []
    for w in weeks:
        model = cp_model.CpModel()
        n = len(w['activities'])
        if not n:
            continue
        # Up to one group per job; this diagnostic has no eight-group cutoff.
        y = [[model.new_bool_var(f'{i}_{k}') for k in range(n)] for i in range(n)]
        for i in range(n):
            model.add_exactly_one(y[i])
            for k in range(i + 1, n):
                model.add(y[i][k] == 0)
        for i, j in w['share']:
            for k in range(n):
                model.add(y[i][k] == y[j][k])
        for constraint in w['limits']:
            used = []
            for k in range(n):
                members = [y[i][k] for i in constraint['members']]
                q = model.new_bool_var('used')
                model.add_max_equality(q, members)
                used.append(q)
                model.add(sum(members) <= constraint['fronts'])
            model.add(sum(used) <= constraint['cap'])
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        solver.parameters.num_search_workers = 1
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE):
            raise RuntimeError(f"Week {w['week']}: grouping check timed out; no feasibility claim can be made")
        if status == cp_model.INFEASIBLE:
            results.append(w['week'])
    return results


if __name__ == '__main__':
    print(json.dumps(check(json.load(sys.stdin))))
