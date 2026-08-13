#!/usr/bin/env bash
# Graph-walk question and rubric synthesis, end to end.
#
# Serves the local model, waits for it, walks every environment's tool graph, executes the chains it finds
# against a private copy of each database, and writes the questions with their rubrics to one JSON file.
#
# Every path and knob lives in this file. Nothing below the CONFIG block needs editing to move this to
# another corpus, model or machine.
#
#   bash run.sh                          # serve the model, then synthesise TARGET questions
#   bash run.sh 1000                     # override the target for this run
#   bash run.sh 1000 --no-serve          # a server is already up at API_BASE
#   bash run.sh --check                  # validate code and corpus without a model
set -euo pipefail

# ------------------------------------------------------------------------------------------ CONFIG

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# the corpus: a directory of <id>/ database folders next to <id>_step4_checkpoint.json files
ENV_DIR="${ENV_DIR:-${HERE}/environment_mix}"

# the local model, served with vLLM. No external API is used anywhere in this pipeline.
MODEL_PATH="${MODEL_PATH:-${HERE}/Qwen3-14B}"
MODEL_NAME="${MODEL_NAME:-qwen3-14b}"
TENSOR_PARALLEL="${TENSOR_PARALLEL:-4}"          # GPUs to shard the model over
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEM_FRACTION="${GPU_MEM_FRACTION:-0.85}"
PORT="${PORT:-8321}"

# further servers of the same model to spread the work over: more replicas on this machine, or other
# machines. Comma-separated OpenAI-compatible base urls; empty to use only the local one.
EXTRA_API_BASES="${EXTRA_API_BASES:-}"

# where the questions and their rubrics are written
OUT="${OUT:-${HERE}/output/questions_graph.json}"
LOG_DIR="${LOG_DIR:-${HERE}/output/logs}"

# how much to generate
TARGET="${TARGET:-1000}"                # total questions to produce, drawn across the corpus; 0 for no limit
ENVS="${ENVS:-0}"                       # environments to use, 0 for the whole corpus
CHAINS="${CHAINS:-4}"                   # ceiling on questions from any single environment
ATTEMPTS="${ATTEMPTS:-40}"              # walks tried per environment to find that many usable chains; walking costs no
                           # model time, so trying harder is cheap and finds noticeably more chains
MIN_STEPS="${MIN_STEPS:-3}"             # a question must rest on at least this many executed tool calls
MAX_STEPS="${MAX_STEPS:-8}"
WORKERS="${WORKERS:-32}"                 # environments processed in parallel, one model call in flight each
SEED="${SEED:-624}"
PYTHON="${PYTHON:-python3}"

# ------------------------------------------------------------------------------------------- RUN

LOCAL_BASE="http://127.0.0.1:${PORT}/v1"
API_BASE="${LOCAL_BASE}${EXTRA_API_BASES:+,${EXTRA_API_BASES}}"
SERVE=1
CHECK=0
for a in "$@"; do
  case "$a" in
    --no-serve) SERVE=0 ;;
    --check) CHECK=1; SERVE=0 ;;
    ''|*[!0-9]*) echo "unrecognised argument: $a" >&2; exit 2 ;;
    *) TARGET=$a ;;
  esac
done

[[ -d "$ENV_DIR" ]] || { echo "environment corpus not found: $ENV_DIR" >&2; exit 1; }
[[ -f "${HERE}/graph_synth.py" ]] || { echo "pipeline script not found: ${HERE}/graph_synth.py" >&2; exit 1; }
mkdir -p "$LOG_DIR"

if [[ $CHECK -eq 1 ]]; then
  "$PYTHON" -m py_compile "${HERE}/graph_syth.py" "${HERE}/graph_synth.py"
  "$PYTHON" "${HERE}/graph_synth.py" --help >/dev/null
  "$PYTHON" - "$ENV_DIR" <<'PY'
import json
import os
import sys

env_dir = os.path.abspath(sys.argv[1])
ids = sorted(
    name.removesuffix("_step4_checkpoint.json")
    for name in os.listdir(env_dir)
    if name.endswith("_step4_checkpoint.json")
)
if not ids:
    raise SystemExit(f"no checkpoints found in {env_dir}")

env_id = ids[0]
checkpoint_path = os.path.join(env_dir, f"{env_id}_step4_checkpoint.json")
database_dir = os.path.join(env_dir, env_id)
if not os.path.isdir(database_dir):
    raise SystemExit(f"database directory missing for {env_id}")
with open(checkpoint_path, encoding="utf-8") as f:
    checkpoint = json.load(f)
tools = checkpoint["data"]["ToolDesignAgent"]["tool_schemas"]
if not any(tool.get("implementation") for tool in tools):
    raise SystemExit(f"no executable tools found in {checkpoint_path}")
print(f"check passed: {len(ids)} environments; sample {env_id} has {len(tools)} tools")
PY
  exit 0
fi

if [[ $SERVE -eq 1 ]]; then
  [[ -e "$MODEL_PATH" ]] || {
    echo "model not found: $MODEL_PATH" >&2
    echo "set MODEL_PATH=/path/to/Qwen3-14B, or use --no-serve with an existing server" >&2
    exit 1
  }
  if curl -sf "${LOCAL_BASE}/models" >/dev/null 2>&1; then
    echo "model already served on port ${PORT}"
  else
    echo "serving ${MODEL_PATH} on port ${PORT} over ${TENSOR_PARALLEL} GPUs"
    nohup "$PYTHON" -m vllm.entrypoints.openai.api_server \
      --model "$MODEL_PATH" --served-model-name "$MODEL_NAME" \
      --tensor-parallel-size "$TENSOR_PARALLEL" --max-model-len "$MAX_MODEL_LEN" \
      --gpu-memory-utilization "$GPU_MEM_FRACTION" --port "$PORT" \
      > "${LOG_DIR}/vllm.log" 2>&1 &
    echo "  waiting for the server (log: ${LOG_DIR}/vllm.log)"
    for _ in $(seq 1 180); do
      curl -sf "${LOCAL_BASE}/models" >/dev/null 2>&1 && break
      sleep 10
    done
    curl -sf "${LOCAL_BASE}/models" >/dev/null 2>&1 || { echo "server did not come up"; tail -30 "${LOG_DIR}/vllm.log"; exit 1; }
    echo "  ready"
  fi
fi

"$PYTHON" "${HERE}/graph_synth.py" \
  --env_dir "$ENV_DIR" --out "$OUT" \
  --api_base "$API_BASE" --model "$MODEL_NAME" \
  --target "$TARGET" --envs "$ENVS" --chains "$CHAINS" --attempts "$ATTEMPTS" \
  --min_steps "$MIN_STEPS" --max_steps "$MAX_STEPS" \
  --workers "$WORKERS" --seed "$SEED" \
  2>&1 | tee "${LOG_DIR}/synth.log"

echo
echo "questions and rubrics: $OUT"