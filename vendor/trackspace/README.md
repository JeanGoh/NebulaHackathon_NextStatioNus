# Active Streamlit scheduling pipeline

The UI uses this checked-in Trackspace handoff, not an external working copy or
the legacy `trackaccess.solve` planner.

The older `optimizer.js` and `feasibility.js` are omitted from this source-only
submission; the active bridge does not import them. This replaces the earlier TrackspaceV2
multi-start integration. The supplied handoff's rules and objective are retained;
the additional modules provide UI diagnostics and alternative enumeration.

- `engine.js`: input expansion, closure/sharing rules, scoring and validation.
- `solver.py`: CP-SAT A/B/C constraints and objective.
- `scheduler.mjs`: runs the solver, validates every chosen/alternative schedule
  and score, and produces the three CSV exports. Invalid output is rejected.
- `request-diagnostics.mjs`: checks consecutive standard accesses beginning at
  each requested start week, before buying ECLO or extra access. Pairwise closure
  checks use the same engine rules. Mandatory sharing chains are checked for
  location sharing limits and contractor workfront limits.
- `check-request-groups.py`: on weeks without an already-proven local failure,
  tests all location and contractor access budgets together. A timeout raises
  an error; it is never reported as feasible. Precedence is checked separately.

## Counting findings

Rule issues and sharing requirements count diagnostic findings. The map merges
findings by location and week: red takes priority over amber. Programme-level
issues such as predecessor order and contractor workfront limits have no single
map location. Contract chips also deduplicate location-weeks, and jump to a week
matching their red/amber issue type. Counts across contracts are not additive.

For `PS1/01_data`, the current requested-date scan returns 49 blocking findings
(38 closure, 5 sharing mix, 4 workfront and 2 precedence) and 124 sharing findings,
covering 138 distinct mapped location-weeks. These are input issues, not violations
in the optimised plans or a count of independently necessary schedule changes.

## Search confidence

The initial A/B/C run returns only the main plans. Each scenario has an optional
button to search up to three alternatives (15 seconds per alternative). Only
that scenario is searched. Each solve excludes the chosen and earlier alternative activity-week/ECLO assignments;
renumbering possession groups does not count as another plan. Every candidate
uses the same rules and objective and is independently checked by `engine.js`.
Candidates are sorted by score. Optional searches never replace the chosen plan
or its downloads; a lower-scoring alternative is highlighted and separately downloadable.

Equal scores are legitimate ties. Rankings from time-limited searches are not
guaranteed. The first solve's lower bound is kept separately: an optimality claim
is limited to the encoded model, its planning horizon and configured group limit.
The score difference is measured in objective points, not raw overdue days.

## Regression checks

Supply the original eight CSV fixtures separately in the ignored `PS1/01_data/`
folder, then run `python -m pytest tests/test_trackspace_handoff.py -q` from the repository root.
Requires Node 20+, the Python dependencies and OR-Tools. It tests closure
exceptions, joint grouping, map severity/deduplication, all three scenario
alternative searches and rejection of invalid schedules/scores.

Full original-dataset check: A 608.3, B 50.0, C 122.4; each chosen plan and three
distinct alternatives pass the bundled validator with zero hard violations.
These checks do not constitute external-validator certification.
