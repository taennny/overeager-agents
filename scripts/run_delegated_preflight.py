"""Execute only the explicitly authorized six-cell 2026-10-30 pilot, serially.

Run from the repo root with PYTHONPATH=. Credentials are read only from the
operator-specified private env file. Nothing prints key values or file contents.
A fresh session directory is required; interrupted sessions are never retried.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

from scope_lab.batch import make_plan, prepare_models, execute_plan
from scope_lab.cli import save_json
from scope_lab.design_v05 import verify_design_review
from scope_lab.provenance import implementation_hash
from scope_lab.readiness import review
from scope_lab.metrics import summarize
from scope_lab.sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    # Parse literals, not executable shell content. Never source user env files.
    allowed={'OPENAI_API_KEY','ANTHROPIC_API_KEY','GPT_MODEL','CLAUDE_MODEL'}
    for line in Path(args.env_file).read_text().splitlines():
        key,sep,value=line.partition('=');key=key.strip().removeprefix('export ')
        if sep and key in allowed:
            parts=shlex.split(value,comments=True)
            if len(parts)!=1:raise ValueError('Invalid private env setting: '+key)
            os.environ[key]=parts[0]
    plan=make_plan(ROOT/'experiments/v05-preflight.json')
    decision=ROOT/'experiments/20261030-delegated-preflight-review.json'
    policy=ROOT/'experiments/20261030-delegated-preflight-budget.json'
    verify_design_review(plan,decision)
    configs=prepare_models(plan)
    image='overeager-sandbox:c04-v02'
    image_id=DockerSandbox(image)._docker(['image','inspect','--format','{{.Id}}',image]).strip()
    code=implementation_hash()
    git_changes=subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,text=True)
    if git_changes.strip():raise ValueError('Commit reviewed code and protocol before paid execution')
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False)
    queue={p:[c for c in plan['trials'] if c['profile']==p] for p in ('gpt','claude')}
    order=[queue[p][i] for i in range(3) for p in ('gpt','claude')]
    frozen_paths=[decision,policy,Path(__file__),ROOT/'docs/experiments/20261030-delegated-preflight-protocol.md']
    frozen={str(p.relative_to(ROOT)):sha(p) for p in frozen_paths}
    manifest=dict(schema_version='delegated-pilot-manifest-v0.1',frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        implementation_sha256=code,image=image,image_id=image_id,plan_id=plan['plan_id'],
        plan=plan,models=configs,decision=json.loads(decision.read_text()),file_sha256=frozen,
        execution_order=[{'trial_id':c['trial_id'],'profile':c['profile'],'scenario_id':c['scenario_id']} for c in order],
        user_reported_approximate_balance_usd={'gpt':4,'claude':4},provider_balance_independently_verified=False,
        provider_cap_usd={'gpt':2,'claude':2},max_trials=6,main_study=False,team_adopted=False)
    save_json(out/'frozen-manifest.json',manifest)
    receipt=dict(status='running',started_at_utc=datetime.now(timezone.utc).isoformat(),trials=[],stop_reason=None)
    save_json(out/'execution-receipt.json',receipt)
    try:
        for cell in order:
            if implementation_hash()!=code or any(sha(ROOT/name)!=value for name,value in frozen.items()):
                raise ValueError('Frozen implementation/protocol changed during execution')
            execute_plan(plan,out/'batch',live=True,limit=1,image=image_id,profile_filter=cell['profile'],
                         design_review=decision,budget_policy=policy,budget_ledger=out/'spend-ledger.json')
            result=json.loads((out/'batch'/cell['trial_id']/'result.json').read_text())
            row={k:result.get(k) for k in ('status','trial_valid','observation_valid','task_success','out_of_scope_observed','scope_compliant_success')}
            row.update(trial_id=cell['trial_id'],profile=cell['profile'],scenario_id=cell['scenario_id'])
            receipt['trials'].append(row)
            save_json(out/'execution-receipt.json',receipt)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            if result['status'] in ('model_error','cleanup_error','setup_error','tool_error','error'):
                receipt.update(status='stopped',stop_reason='Execution/model/budget error; preserve and review, no retry')
                break
        else:
            receipt['status']='completed_six_trials'
    except Exception as exc:
        receipt.update(status='stopped',stop_reason=type(exc).__name__)
        raise
    finally:
        receipt['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        save_json(out/'execution-receipt.json',receipt)
        if (out/'batch/plan.json').exists():
            save_json(out/'readiness.json',review(out/'batch'))
            reports={c['trial_id']:json.loads((out/'batch'/c['trial_id']/'result.json').read_text())
                     for c in plan['trials'] if (out/'batch'/c['trial_id']/'result.json').exists()}
            save_json(out/'metrics.json',summarize(plan,reports))
    return 0 if receipt['status']=='completed_six_trials' else 2


if __name__=='__main__':
    raise SystemExit(main())
