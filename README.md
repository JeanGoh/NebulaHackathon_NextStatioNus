# NextStatioNUS — Hackathon source submission

Streamlit railway programme planner powered by the bundled Trackspace rule
engine and an OR-Tools CP-SAT solver. Upload eight programme CSV files, review
requested-date conflicts, compare Scenario A/B/C, and download validated plans.

This repository contains the final application source, active solver, setup
files, documentation and active-pipeline regression test code. It deliberately
excludes input datasets, generated schedules, screenshots, secrets, local
environments and the development repository's Git history.

## Run locally

Requires Python 3.10+ and Node.js 20+.

```bash
git clone https://github.com/JeanGoh/NebulaHackathon_NextStatioNus.git
cd NebulaHackathon_NextStatioNus
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Upload your eight CSVs through the sidebar. No dataset is bundled or loaded
automatically. The optional Ask assistant uses `ANTHROPIC_API_KEY`; scheduling
works without it. Never commit a real key.

## Implementation

| Responsibility | Source |
|---|---|
| UI, maps, downloads and Ask context | `app.py`, `src/trackaccess/` |
| Python-to-Node bridge | `src/trackaccess/trackspace_bridge.py` |
| Trackspace rules, scoring and validation | `vendor/trackspace/engine.js` |
| Scenario A/B/C CP-SAT solver | `vendor/trackspace/solver.py` |
| Orchestration, validation gate and exports | `vendor/trackspace/scheduler.mjs` |
| Requested-date diagnostics | `vendor/trackspace/request-diagnostics.mjs`, `check-request-groups.py` |

The UI's active scheduling path is **Trackspace**, not the older Python solver.
Some compatibility Python modules remain because the application imports them;
they must not be used to reproduce current scenario results. Unused historical
JavaScript optimisers and historical specifications are not included.

Main plans run sequentially, with a 120-second search limit per scenario.
Alternative searches are opt-in, up to three 15-second searches per scenario.
Every offered schedule passes the bundled engine's validation and score check.
This is not independent external certification or a guarantee of global
optimality beyond the encoded model and search limits.

## Documentation

- [Setup, inputs and optional Ask API](docs/SETUP.md)
- [Solver constraints, scoring and scenarios](docs/SOLVER.md)
- [Cloud Run packaging and deployment](docs/CLOUD_RUN.md)
- [Submission contents and verification](docs/CURRENT_HANDOFF.md)
- [Active engine and diagnostic counts](vendor/trackspace/README.md)

## Verification

The regression code is included, but the original eight CSV test fixtures are
not. Place them locally in the ignored `PS1/01_data/` folder before running:

```bash
python -m pytest tests/test_trackspace_handoff.py tests/test_trackspace_view.py -q
```

The clean copy passed all nine active-pipeline tests using local original CSV
fixtures, and its Streamlit startup check passed.
See the handoff for packaging checks and limitations. The Cloud Run files are
prepared; their presence does **not** mean a cloud deployment has completed.

Uploaded files and results are session-local. Restarting the app or losing a
session can require a fresh upload and solve. Download results before leaving.
