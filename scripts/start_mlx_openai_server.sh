#!/usr/bin/env bash
# Start mlx-openai-server for multi-user EE-Wiki (generation.llm_backend: openai).
#
# Usage:
#   export EE_WIKI_MODELS_DIR=/path/to/models
#   ./scripts/start_mlx_openai_server.sh
#
# Override via env:
#   MLX_MODEL_NAME=Qwen3-30B-A3B-Instruct-2507-MLX-4bit
#   MLX_HOST=127.0.0.1 MLX_PORT=8000
#   MLX_DECODE_CONCURRENCY=4 MLX_PROMPT_CONCURRENCY=2
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${EE_WIKI_MODELS_DIR:-}" ]]; then
  echo "ERROR: set EE_WIKI_MODELS_DIR to your local models directory." >&2
  exit 1
fi

MODEL_NAME="${MLX_MODEL_NAME:-Qwen3-30B-A3B-Instruct-2507-MLX-4bit}"
MODEL_PATH="${EE_WIKI_MODELS_DIR%/}/${MODEL_NAME}"
HOST="${MLX_HOST:-127.0.0.1}"
PORT="${MLX_PORT:-8000}"
DECODE_CONCURRENCY="${MLX_DECODE_CONCURRENCY:-4}"
PROMPT_CONCURRENCY="${MLX_PROMPT_CONCURRENCY:-2}"

if [[ ! -d "$MODEL_PATH" ]]; then
  echo "ERROR: model path not found: $MODEL_PATH" >&2
  exit 1
fi

if ! command -v mlx-openai-server >/dev/null 2>&1; then
  echo "ERROR: mlx-openai-server not found in PATH." >&2
  echo "Install in this venv: pip install mlx-openai-server" >&2
  exit 1
fi

echo "Starting mlx-openai-server on ${HOST}:${PORT}"
echo "Model: ${MODEL_PATH}"

exec mlx-openai-server launch \
  --model-type lm \
  --model-path "$MODEL_PATH" \
  --served-model-name "$MODEL_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --decode-concurrency "$DECODE_CONCURRENCY" \
  --prompt-concurrency "$PROMPT_CONCURRENCY"
