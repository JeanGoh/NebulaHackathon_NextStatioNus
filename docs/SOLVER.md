# Active solver implementation

## Data path

`app.py` calls `src/trackaccess/trackspace_bridge.py`, which invokes
`vendor/trackspace/scheduler.mjs`. The scheduler loads CSVs through `engine.js`,
builds a payload, and runs `solver.py` with Python OR-Tools CP-SAT. The JavaScript
engine validates every returned schedule and recomputes its score before it is
displayed or exported. A disagreement is an error, not a usable plan.

No external Documents/Downloads folder is used at runtime. The old Python
`trackaccess.solve` and old JavaScript mutation search are not this pipeline.

## Decision variables and constraints

For each activity and eligible week, `x` selects standard access and `e` selects
ECLO with `e <= x`. Possession assignment uses a group variable and binary group
indicators. A standard access supplies one work unit; ECLO supplies 1.5, encoded
as `sum(2*x + e) >= 2*required_work`. At most one access is scheduled per activity
per week. Starts respect requested release weeks; a predecessor must finish in
an earlier week than its successor starts.

Route and closure footprints come from `engine.js`. Incompatible overlapping
closures cannot run in the same week. Legal direct co-sharing requires the same
possession label; the specified unoccupied platform-only buffer exception is
preserved. Co-sharing exemptions are not generally transitive. Location groups
have at most four activities and the allowed access-type mix; contractor/type
groups obey workfront and weekly-access limits.

The UI configures the input planning horizon and eight possession groups.
These are model limits, not a claim about every possible real-world schedule.

## Scenarios

| Scenario | Timing / access rules | Objective |
|---|---|---|
| A — Protect the track | Nominal location capacity; no ECLO; lateness allowed | Weighted contract delay |
| B — Hit every deadline | No late completion; ECLO and excess location access allowed within the remaining rules | 5 × ECLO activity-accesses + 7 × extra access-nights |
| C — Balanced | Lateness allowed; at most one excess possession per location-week; ECLO within a two-consecutive-week window per affected line | Weighted contract delay + ECLO and extra-access costs |

Weighted delay sums each activity's contribution using its contract's completion
delay in days. Contract priority weights are 100, 10 and 1; activity multipliers
are 1.3, 1.2 and 1.0. The score is **not** raw overdue days. For example, a plan
with fewer total late days may cost more when those days affect higher-priority
contracts. The solver uses integer-scaled costs and minimises booked accesses
as a secondary tie-break after the primary score.

## Requested-date diagnostics

Diagnostics assume consecutive standard accesses from each requested start.
They check predecessor order, horizon, pairwise closures, mandatory sharing
chains, sharing mix, workfronts and location/contractor budgets. For weeks not
already locally disproved, `check-request-groups.py` tests joint grouping.
Diagnostic timeouts are errors, not feasibility claims.

Rule findings count checks, while map cells deduplicate by location and week.
Red overrides amber at the same cell. Programme-level findings need not have a
map location. Sharing requirements do not by themselves prove the entire
requested programme fits. Requested flags are not residual violations in a
validated optimised plan.

## Confidence and optional alternatives

Main runs do not search alternatives automatically. An explicit per-scenario
request validates the chosen seed and excludes its activity-week/ECLO assignment.
Up to three further solves each exclude earlier assignments. Changing only group
numbers does not count as a distinct schedule. Every candidate is validated.

Optional search never mutates the chosen submission, report, main CSVs or another
scenario. A better alternative is highlighted but remains a separate download.
Failures leave the original result intact. Equal scores are legitimate ties.

The main solve's bound is shown separately from actual alternatives. Matching
that bound establishes the primary-score optimum only for the encoded model and
configured limits. Time-limited candidate rankings are not guaranteed, and the
gap is not a statistical confidence percentage.

## Operational views and assistant

The map counts ECLO activity-accesses once rather than once per occupied location.
Extra access is counted separately above nominal location capacity. Capacity
alerts identify nominally full worksites, not a proof of no rescheduling slack.
The preview does not commit a schedule or tell contractors to start work.

The Ask API receives the current result snapshot and read-only tools for selected
weeks, contracts, diagnostics and scenario/alternative scores. It cannot switch
to the old optimiser to make recommendations. Unavailable closure metadata is
not silently replaced with legacy footprints. Answers are cleared when context
changes; generated prose still requires human review.

## Validation boundary

Validation is the bundled handoff's implementation, not certification from a
separate external service. Regression checks cover closure exceptions, joint
grouping, scenario outputs, alternatives, map counts, API grounding and export
consistency. External acceptance checks should still be run when required.
