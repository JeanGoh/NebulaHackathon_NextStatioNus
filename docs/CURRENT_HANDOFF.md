# Source-only handoff — 19 September 2026

## Scope

- Final Streamlit app and supporting Python modules.
- Active Trackspace engine, diagnostics, CP-SAT solver and orchestration.
- Dependencies, dark theme configuration and a placeholder secrets example.
- Local setup, solver documentation and Cloud Run deployment configuration.
- Nine active-pipeline regression tests and their JavaScript test helper.

No input datasets, generated schedules, challenge attachments, screenshots,
API keys, passwords or previous Git history are included. The old JavaScript
`optimizer.js` and `feasibility.js` are not part of the active pipeline and have
been omitted. Supporting Python compatibility modules are retained to preserve
the application's import dependencies; current scheduling uses Trackspace.

## Verification and limitations

The source application's focused Trackspace/UI/API suite passed **9 tests**
before packaging and again from this clean copy using the original dataset
locally (not included in Git). A Streamlit AppTest startup check passed, and
the app plus active engine/solver sources are byte-identical to the source
project. Original-dataset main scores previously checked were
A **608.3**, B **50.0**, C **122.4**, with zero bundled-validator hard violations.
Those numbers are dataset-specific, not promised outputs for other inputs.
API request construction uses a mocked client in tests, not a paid live call.

The original development repository's last full suite had **62 passed, 1 failed**
in a legacy Python request-placement test. This submission includes the active
regression suite only; it does not imply every historical test passed.

To rerun dataset-dependent regressions, provide the original eight CSV files in
`PS1/01_data/` locally. That folder is ignored and must not be committed to this
source-only repository. App users can upload their own dataset through the UI
without creating this folder.

Cloud Run's Dockerfile and startup script are prepared, but the container has
not yet been built or deployed. No claim of live cloud verification is made.
No API key has been migrated to Google Cloud. A public demo with a paid Ask API
needs additional budget controls and access/rate limiting.

Plans remain previews. No durable publication or approval workflow is included.
Session uploads/results may be lost on restart or reconnect. Search bounds and
validation apply to the bundled model, horizon and configured group limits;
external acceptance validation should still be performed when required.
