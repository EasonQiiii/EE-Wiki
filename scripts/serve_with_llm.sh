#!/usr/bin/env bash
# Start EE-Wiki API after verifying a local OpenAI-compatible LLM server.
# Usage: ./scripts/serve_with_llm.sh [serve.py args...]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BASE_URL="${EE_WIKI_OPENAI_BASE_URL:-http://127.0.0.1:8000/v1}"
HEALTH_URL="${BASE_URL%/v1}/health"

if ! curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
  echo "ERROR: LLM server not reachable at $HEALTH_URL" >&2
  echo "Start mlx-openai-server first: ./scripts/start_mlx_openai_server.sh" >&2
  echo "See docs/usage/local-setup.md#multi-user-rag-single-mac." >&2
  exit 1
fi

echo "LLM server OK at $HEALTH_URL"
exec python scripts/serve.py "$@"
