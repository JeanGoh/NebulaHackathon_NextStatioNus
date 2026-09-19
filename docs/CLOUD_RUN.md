# Cloud Run demo deployment

The Dockerfile packages Python 3.12, Node 22 and the existing Trackspace solver.
It does not modify scheduling rules or search time limits. Only application
code and theme configuration are copied into the image: no uploaded CSVs,
historical submissions, API keys or local credentials are included.

## Build and deploy

Use Google Cloud Shell signed into the intended project. A hackathon/Qwiklabs
project can expire; do not rely on it for permanent hosting. Builds, image
storage and active Cloud Run sessions can consume project credits/cost money.

Clone the GitHub repository and check out the intended commit before deploying.
If the clone already exists, inspect its status before updating it; do not
overwrite local changes.

```bash
git clone https://github.com/JeanGoh/NebulaHackathon_NextStatioNus.git
cd NebulaHackathon_NextStatioNus
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project=PROJECT_ID
gcloud run deploy nextstationnus \
  --source=. --project=PROJECT_ID --region=us-central1 \
  --port=8080 --cpu=2 --memory=4Gi \
  --min=0 --max=1 --concurrency=10 \
  --timeout=3600 --session-affinity \
  --no-allow-unauthenticated
```

Replace `PROJECT_ID`. The command starts private; grant public invocation only
after the owner has approved public access. For a new public demo, use
`--allow-unauthenticated` in place of `--no-allow-unauthenticated`. On an existing
service, verify its IAM policy; the latter flag is not a substitute for auditing
existing public bindings. Never change organisation restrictions to bypass a
lab policy. A build-permissions error needs a project administrator's review;
do not grant broad Editor/Owner roles to solve it.

Two vCPUs and 4 GiB are a demo starting point, not a performance guarantee.
The solver retains its existing eight search workers; concurrent users share
the instance's CPU and memory. The request concurrency accommodates Streamlit
HTTP and WebSocket requests, not ten simultaneous optimisations. One instance
limits scaling, not total spending, and excess requests can queue or fail.

## Secrets and public access

The optional Ask bar needs `ANTHROPIC_API_KEY`. No key is included or migrated
automatically. Store it in Secret Manager and grant the runtime service account
access only to that secret if the project owner approves. Do not place it in
the Dockerfile, GitHub, command history or build arguments. Planning works
without it. Enabling a paid model on an unrestricted public app also exposes
the API budget to visitors; add authentication/rate limits before doing so.

## Verify after deployment

1. Check the deployed revision is ready and note its image digest/commit.
2. Open the service URL and confirm the NextStatioNUS landing page loads.
3. Upload eight CSVs, check diagnostics, run A/B/C and inspect validation status.
4. Download each scenario's current CSVs and verify the exported results.
5. Check Cloud Run logs for startup, missing runtime and memory errors.

Streamlit uses WebSockets. A one-hour request timeout and session affinity
help demo sessions but do not make them durable. Instance restarts, deployment,
scale-to-zero and reconnects can lose session data. Download results before
leaving. The app is a demo, not persistent shared operational storage.

## References

- https://docs.cloud.google.com/run/docs/deploying-source-code
- https://docs.cloud.google.com/run/docs/triggering/websockets
- https://cloud.google.com/run/pricing
