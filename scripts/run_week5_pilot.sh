#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
phase="${1:?Usage: bash scripts/run_week5_pilot.sh preflight|pilot NEW_OUTPUT_DIRECTORY [PASSED_PREFLIGHT_AUDIT]}"
run_output="${2:?Choose a new output directory}"
if [[ -e "$run_output" ]]; then echo 'Output already exists; review it manually rather than overwrite.' >&2; exit 2; fi
case "$phase" in
  preflight) run_config=experiments/v04-preflight.json; run_limit=3 ;;
  pilot)
    python3 - "${3:?Provide a passed preflight audit}" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
if r.get('compatibility_gate')!='ready_for_team_review':
    raise SystemExit('Preflight is not ready; inspect failure evidence before expansion.')
PY
    run_config=experiments/v04-pilot.json; run_limit=24 ;;
  *) echo 'Phase must be preflight or pilot' >&2; exit 2 ;;
esac
export QWEN_BACKEND=ollama EXAONE_BACKEND=ollama
export QWEN_MODEL="${QWEN_MODEL:-qwen3:8b}" EXAONE_MODEL="${EXAONE_MODEL:-exaone3.5:7.8b}"
export QWEN_BASE_URL="${QWEN_BASE_URL:-http://127.0.0.1:11435}"
export EXAONE_BASE_URL="${EXAONE_BASE_URL:-$QWEN_BASE_URL}"
export QWEN_OLLAMA_FORMAT=json EXAONE_OLLAMA_FORMAT=json
run_image="${SCOPE_V03_IMAGE:-overeager-sandbox:v03}"
if [[ "$phase" == pilot ]]; then
  python3 - "$3" "$run_image" <<'CHECK'
import json,sys
from pathlib import Path
from scope_lab.batch import make_plan
from scope_lab.model_client import profile_config,model_provenance
from scope_lab.provenance import implementation_hash
from scope_lab.readiness import review
from scope_lab.sandbox import DockerSandbox
folder=Path(sys.argv[1]).resolve().parent
lock=json.loads((folder/'plan.json').read_text())
expected=make_plan('experiments/v04-preflight.json')
if lock['plan'] != expected or lock['implementation_hash'] != implementation_hash():
    raise SystemExit('Preflight code/assets/config differ; run a new preflight.')
if review(folder)['compatibility_gate']!='ready_for_team_review':
    raise SystemExit('Preflight source results are not ready.')
image=DockerSandbox(sys.argv[2])._docker(['image','inspect','--format','{{.Id}}',sys.argv[2]]).strip()
if image != lock['image_id']:
    raise SystemExit('Image changed since preflight.')
for profile, previous in lock['models'].items():
    config=profile_config(profile)
    config.update({k:expected['config']['inference'][k] for k in ('num_ctx','max_tokens')})
    config['provenance']=model_provenance(config)
    if config != previous:
        raise SystemExit('Model/runtime/settings changed since preflight.')
CHECK
fi
for run_profile in qwen exaone; do
  python3 -m scope_lab.batch run --config "$run_config" --out "$run_output" \
    --image "$run_image" --live --profile "$run_profile" --limit "$run_limit"
done
python3 -m scope_lab.metrics "$run_output" --out "$run_output/summary.json"
python3 -m scope_lab.readiness "$run_output" --out "$run_output/readiness.json"
