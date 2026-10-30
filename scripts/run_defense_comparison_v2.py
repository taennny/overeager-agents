"""Run the explicitly authorized, cumulatively bounded defense comparison.

Six new matching-code feasibility trials gate 24 separate comparison trials.
All trials are serial. Historical evidence and spending are never overwritten.
"""
import argparse
from datetime import datetime, timezone
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
from scripts.run_delegated_preflight import sha

ROOT=Path(__file__).resolve().parents[1]
STOP_STATUSES={'model_error','cleanup_error','setup_error','tool_error','error'}


def interleave(plan):
    queues={p:[c for c in plan['trials'] if c['profile']==p] for p in ('gpt','claude')}
    return [queues[p][i] for i in range(len(queues['gpt'])) for p in ('gpt','claude')]



def can_continue_accounted_error(report, ledger, trial_id, phase):
    if report.get('status') != 'model_error' or phase != 'core':
        return False
    events = report.get('agent', {}).get('events', [])
    diagnostics = (events[-1].get('model_diagnostics') or {}) if events else {}
    accounted = [r for r in ledger['requests'] if r['trial_id'] == trial_id]
    return (bool(diagnostics.get('usage')) and bool(accounted)
            and all(r['status'] == 'settled' for r in accounted)
            and accounted[-1].get('response_outcome') == 'model_error_with_known_usage')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file',required=True);p.add_argument('--out',required=True)
    args=p.parse_args()
    allowed={'OPENAI_API_KEY','ANTHROPIC_API_KEY','GPT_MODEL','CLAUDE_MODEL'}
    for line in Path(args.env_file).read_text().splitlines():
        key,sep,value=line.partition('=');key=key.strip().removeprefix('export ')
        if sep and key in allowed:
            parts=shlex.split(value,comments=True)
            if len(parts)!=1:raise ValueError('Invalid private setting: '+key)
            os.environ[key]=parts[0]
    decision=ROOT/'experiments/20261030-defense-comparison-v2-review.json'
    policy=ROOT/'experiments/20261030-defense-comparison-v2-budget.json'
    protocol=ROOT/'docs/experiments/20261030-defense-comparison-v2-protocol.md'
    plans={phase:make_plan(ROOT/('experiments/v05-'+phase+'.json')) for phase in ('preflight','core')}
    for plan in plans.values():verify_design_review(plan,decision)
    configs=prepare_models(plans['core'])
    image='overeager-sandbox:c04-v02'
    image_id=DockerSandbox(image)._docker(['image','inspect','--format','{{.Id}}',image]).strip()
    code=implementation_hash()
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,text=True).strip():
        raise ValueError('Commit the protocol and checked code before paid execution')
    frozen_paths=[decision,policy,protocol,Path(__file__),ROOT/'scripts/run_delegated_preflight.py']
    frozen={str(path.relative_to(ROOT)):sha(path) for path in frozen_paths}
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False)
    manifest=dict(schema_version='defense-comparison-manifest-v0.1',frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        implementation_sha256=code,image=image,image_id=image_id,plans=plans,models=configs,
        decision=json.loads(decision.read_text()),budget_policy=json.loads(policy.read_text()),file_sha256=frozen,
        execution_order={phase:[{k:c[k] for k in ('trial_id','profile','scenario_id','defense')} for c in interleave(plan)]
                         for phase,plan in plans.items()},
        preflight_trials=6,comparison_trials=24,max_new_trials=30,main_study=False,team_adopted=False,
        cumulative_provider_cap_usd={'gpt':2,'claude':2})
    save_json(out/'frozen-manifest.json',manifest)
    receipt=dict(status='running',started_at_utc=datetime.now(timezone.utc).isoformat(),trials=[],stop_reason=None)
    save_json(out/'execution-receipt.json',receipt)
    try:
        stopped=False
        for phase,plan in plans.items():
            for cell in interleave(plan):
                if implementation_hash()!=code or any(sha(ROOT/name)!=value for name,value in frozen.items()):
                    raise ValueError('Frozen implementation or terms changed during execution')
                execute_plan(plan,out/phase,live=True,limit=1,image=image_id,profile_filter=cell['profile'],
                    preflight=out/'preflight' if phase=='core' else None,design_review=decision,
                    budget_policy=policy,budget_ledger=out/'spend-ledger.json')
                report=json.loads((out/phase/cell['trial_id']/'result.json').read_text())
                row={k:report.get(k) for k in ('status','trial_valid','observation_valid','task_success','out_of_scope_observed','scope_compliant_success')}
                row.update(phase=phase,**{k:cell[k] for k in ('trial_id','profile','scenario_id','defense')})
                receipt['trials'].append(row);save_json(out/'execution-receipt.json',receipt)
                print(json.dumps(row),flush=True)
                ledger = json.loads((out/'spend-ledger.json').read_text())
                known_response_error = can_continue_accounted_error(report, ledger, cell['trial_id'], phase)
                if report['status'] in STOP_STATUSES and not known_response_error:
                    receipt.update(status='stopped',stop_reason='Execution/model/budget error; preserve without retry')
                    stopped=True;break
            if stopped:break
            if phase=='preflight':
                readiness=review(out/'preflight');save_json(out/'preflight-readiness.json',readiness)
                if readiness['compatibility_gate']!='ready_for_team_review':
                    receipt.update(status='stopped',stop_reason='New matching-code preflight did not satisfy capability gate')
                    break
        else:
            receipt['status']='completed_preflight_6_and_core_24'
    except Exception as exc:
        receipt.update(status='stopped',stop_reason=type(exc).__name__)
        raise
    finally:
        receipt['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        save_json(out/'execution-receipt.json',receipt)
        for phase,plan in plans.items():
            if not (out/phase/'plan.json').exists():continue
            reports={c['trial_id']:json.loads((out/phase/c['trial_id']/'result.json').read_text())
                     for c in plan['trials'] if (out/phase/c['trial_id']/'result.json').exists()}
            save_json(out/(phase+'-metrics.json'),summarize(plan,reports))
    return 0 if receipt['status']=='completed_preflight_6_and_core_24' else 2


if __name__=='__main__':raise SystemExit(main())
