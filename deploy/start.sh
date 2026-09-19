#!/bin/sh
set -eu

# exec forwards Cloud Run's shutdown signal to Streamlit. Keep CORS/XSRF
# protections enabled; Cloud Run terminates HTTPS in front of this HTTP port.
exec python -m streamlit run /app/app.py \
  --server.address=0.0.0.0 \
  --server.port="${PORT:-8080}" \
  --server.headless=true \
  --server.fileWatcherType=none \
  --browser.gatherUsageStats=false
