#!/usr/bin/env bash
set -euo pipefail
# This is a Linux/NVIDIA deployment recipe, not a macOS installer.
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This serving recipe requires the research Linux GPU server." >&2
  exit 2
fi
command -v nvidia-smi >/dev/null || { echo "NVIDIA driver / nvidia-smi missing" >&2; exit 2; }
command -v vllm >/dev/null || { echo "Install the reviewed vLLM version in a dedicated environment first" >&2; exit 2; }
: "${VLLM_API_KEY:?Set VLLM_API_KEY on the GPU host; never put it in command arguments}"
case "${1:-}" in
  qwen) task_model="${QWEN_MODEL:-Qwen/Qwen3-8B}" ;;
  exaone) task_model="${EXAONE_MODEL:?Set the exact agreed EXAONE_MODEL identifier}" ;;
  *) echo "Usage: bash serving/serve.sh qwen|exaone" >&2; exit 2 ;;
esac
# One GPU: start ONE model at a time. Use SSH forwarding to access from a Mac.
exec vllm serve "$task_model" \
  --host 127.0.0.1 --port "${SERVE_PORT:-8000}" \
  --tensor-parallel-size 1 \
  --max-model-len "${MAX_MODEL_LEN:-4096}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.85}" \
  --generation-config vllm

