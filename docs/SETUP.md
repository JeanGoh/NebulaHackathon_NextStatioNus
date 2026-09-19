# Setup and operation

## Requirements

- Python 3.10 or newer and pip; local verification used Python 3.14.7.
- Node.js 20 or newer on PATH; local verification used Node 24.21.0.
- Python packages from the repository's `requirements.txt`.
- No npm dependencies are needed for the vendored scheduler.

The Streamlit process starts Node, which starts OR-Tools using the same Python
interpreter as the app. Both runtimes must be installed on the deployment host.

## macOS / Linux

```bash
git clone https://github.com/JeanGoh/NebulaHackathon_NextStatioNus.git
cd NebulaHackathon_NextStatioNus
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
node --version
python -m streamlit run app.py
```

## Windows PowerShell

```powershell
git clone https://github.com/JeanGoh/NebulaHackathon_NextStatioNus.git
cd NebulaHackathon_NextStatioNus
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
node --version
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local address printed by Streamlit. The app starts on the upload page;
it does not load any dataset or schedule automatically.

## Optional Ask assistant

The scheduler does not need an API key. The optional Ask bar uses Anthropic;
it does not use a GitHub token or an OpenAI API key.

Create `.streamlit/secrets.toml` locally using the example file, or supply
`ANTHROPIC_API_KEY` through your host's secret settings. Never commit the real
file, put it in a ZIP submission, or paste the key into an issue.

The assistant receives the selected Trackspace scenario, current rule findings,
validation report and generated alternative scores. Its tools are read-only.
The prose is model-generated, so critical operational decisions still require
review; it cannot certify that an untested reschedule will work.

## Input and exports

Upload your eight numbered CSV files together, keeping their required headers:

1. `01_LINES.csv`
2. `02_STATIONS.csv`
3. `03_SECTORS.csv`
4. `04_LOCATION_SUPPLY.csv`
5. `05_BUFFER_LOCATION.csv`
6. `06_PARAMETERS.csv`
7. `07_PROJECT_DETAILS.csv`
8. `08_ACTIVITY_DETAILS.csv`

Datasets are deliberately not included in this source-only repository.

Run A/B/C, then download `SCHEDULE_ACCESS.csv`, `SCHEDULE_OCCUPANCY.csv` and
`RESULTS.csv`. Comparison-page ZIPs put the three files at the ZIP root;
the selected-plan sidebar ZIP places them under its scenario folder.
Both contain the selected current schedule. Alternative ZIPs are separate.

Generate fresh downloads from your current uploaded programme; no precomputed
schedule outputs are included in this repository.

## Existing Streamlit deployment

Configure the app entry point as `app.py`, with repository root as its working
directory. Keep `requirements.txt`, `packages.txt`, `.streamlit/config.toml`
and `vendor/trackspace/` in the deployment. Confirm the host supplies Node 20+;
the OS package name alone does not guarantee its version. Set the API key in
deployment secrets, not GitHub. A push updates source; verify the host's build
logs and refresh the app after deployment before testing downloads.

## Performance and state

For a container-based Google Cloud deployment, see [Cloud Run](CLOUD_RUN.md).
The Dockerfile installs both runtimes and excludes local secrets and datasets.

The three main plans run sequentially, with up to 120 seconds per solve plus
setup/validation. Alternatives are opt-in per scenario, with up to three
15-second searches. A dependency probe is cached for five minutes.
Rules, validation gates and main-search time limits have not been weakened.

The app keeps uploaded data in temporary local storage and results in session
state. A restart or lost session can require re-uploading and rerunning. This is
not durable multi-user storage or an operational schedule publication system.

## Checks and troubleshooting

Before running the regression suite, place the original eight programme CSV
fixtures in `PS1/01_data/` locally. This folder is ignored and is not uploaded.
The suite asserts original-dataset results, so arbitrary CSVs are not equivalent
test fixtures. Running the app itself does not require this folder.

```bash
python -m pytest tests/test_trackspace_handoff.py tests/test_trackspace_view.py -q
python -m pytest -q
```

- Missing Node/OR-Tools: install the required runtime into the host running the app.
- Ask bar unavailable: check the secret and Anthropic dependency; planning still works.
- No feasible result: review the status and inputs. A time limit does not prove
  impossibility; even a model-infeasible result is subject to horizon/group limits.
- Old screen after an update: rerun the app and, if needed, rerun A/B/C.
- Optional search failure: the main plan and its downloads remain unchanged.

See `CURRENT_HANDOFF.md` for verification scope and deployment limitations.
