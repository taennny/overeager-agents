"""Frozen D0 extension: three archived runs plus 27 new runs per model.

Uses the existing harness unchanged. Every slot runs at most once. Closed
uncertain calls retain their full cost reservation; they are never called free
or settled. A fixed number of such errors and the cumulative dollar cap bound
continuation. In-flight calls block crash recovery.
"""
import argparse
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import uuid

from scope_lab.agent import build_system_prompt
from scope_lab.batch import make_plan, digest, prepare_models, scenario_fingerprint
from scope_lab.cli import read_json, save_json
from scope_lab.harness import run, load_scenario
from scope_lab.model_client import ModelError, make_completion, inference_metadata, model_provenance
from scope_lab.provenance import implementation_hash
from scope_lab.sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[1]
MODELS = {'gpt':'gpt-5.4-mini-2026-03-17', 'claude':'claude-haiku-5-5'}
ENDPOINTS = {'gpt':'https://api.openai.com/v1', 'claude':'https://api.anthropic.com/v1'}
RATES = {'gpt':(750,4500), 'claude':(1000,2500)}
CONFIG = ROOT/'experiments/20261104-d0-30-each.json'
DECISION = ROOT/'experiments/20261104-d0-30-each-decision.json'


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_env(path):
    for line in Path(path).read_text().splitlines():
        key,sep,value=line.partition('=');key=key.strip().removeprefix('export ')
        if sep and key in {'OPENAI_API_KEY','ANTHROPIC_API_KEY','GPT_MODEL','CLAUDE_MODEL'}:
            parts=shlex.split(value,comments=True)
            if len(parts)!=1:raise ValueError('Invalid private setting: '+key)
            os.environ[key]=parts[0]


def validate_plan(plan, decision):
    template=read_json(ROOT/'experiments/v05-preflight.json')
    config=dict(plan['config']);config.update(repeats=template['repeats'],experiment_id=template['experiment_id'])
    if (config!=template or plan['config']['repeats']!=10
            or plan['config']['experiment_id']!='v05-d0-30-each-20261104' or len(plan['trials'])!=60
            or len({c['trial_id'] for c in plan['trials']})!=60
            or decision.get('schema_version')!='baseline-extension-decision-v0.1'
            or decision.get('plan_id')!=plan['plan_id']
            or decision.get('assets_digest')!=digest(sorted({c['fingerprint'] for c in plan['trials']}))
            or decision.get('decision_maker')!='AI under user delegation'
            or decision.get('team_adopted') is not False or decision.get('independent_human_review') is not False
            or not decision.get('user_authorization') or decision.get('target_per_model')!=30):
        raise ValueError('Extension must be the authorized fixed D0 30-per-model matrix')
    new=[c for c in plan['trials'] if c['repeat']>0]
    if Counter(c['profile'] for c in new)!=Counter({'gpt':27,'claude':27}):
        raise ValueError('Exactly 27 new slots per model required')
    return new


def verify_legacy(plan, decision):
    refs=decision['legacy_reports']
    if len(refs)!=6:raise ValueError('Exactly six distinct archived reports required')
    slots={(c['profile'],c['scenario_id']):c for c in plan['trials'] if c['repeat']==0}
    seen=set();result=[]
    for ref in refs:
        path=(ROOT/ref['path']).resolve()
        if ROOT not in path.parents or file_sha(path)!=ref['sha256']:
            raise ValueError('Archived report hash/path differs')
        report=read_json(path);cell=report['cell'];pair=(cell['profile'],cell['scenario_id'])
        if pair in seen or pair not in slots:raise ValueError('Duplicate or wrong archived slot')
        seen.add(pair);slot=slots[pair]
        scenario,_,evaluator=load_scenario(slot['scenario'])
        expected_system=build_system_prompt(True,'environment-v2',True)
        if (report.get('status')!='finished' or report.get('trial_valid') is not True
                or report.get('observation_valid') is not True or report.get('defense')!='D0'
                or cell['fingerprint']!=slot['fingerprint'] or report['image_id']!=decision['image_id']
                or report['model']['model_requested']!=MODELS[pair[0]]
                or report['prompt_sha256']!=hashlib.sha256(scenario['prompt'].encode()).hexdigest()
                or report['system_prompt_sha256']!=hashlib.sha256(expected_system.encode()).hexdigest()
                or report['evaluator_sha256']!=hashlib.sha256(evaluator.encode()).hexdigest()):
            raise ValueError('Archived inputs/scorer/model/image do not match the D0 extension')
        result.append(dict(slot_id=slot['trial_id'],source_session='delegated-preflight-20261030-budget2',
                           source_trial_id=cell['trial_id'],path=ref['path'],sha256=ref['sha256']))
    return result


def prior_floor(policy):
    source=policy['prior']
    ledger_path=(ROOT/source['ledger_path']).resolve();receipt_path=(ROOT/source['receipt_path']).resolve()
    if (ROOT not in ledger_path.parents or ROOT not in receipt_path.parents
            or file_sha(ledger_path)!=source['ledger_sha256'] or file_sha(receipt_path)!=source['receipt_sha256']):
        raise ValueError('Prior ledger/closed receipt differs')
    ledger=read_json(ledger_path);receipt=read_json(receipt_path)
    if receipt.get('status')!='stopped' or not receipt.get('finished_at_utc'):
        raise ValueError('Prior session is not closed')
    floor=ledger['carried_forward_debit_nano_usd']
    if set(floor)!=set(MODELS) or any(type(x) is not int or x<0 for x in floor.values()):
        raise ValueError('Invalid inherited cost floor')
    totals=dict(floor)
    for row in ledger['requests']:
        name=row['profile'];charge=row['debit_nano_usd']
        if name not in MODELS or type(charge) is not int or charge<0:raise ValueError('Invalid previous charge')
        if row['status']!='settled':
            reserve=135168*RATES[name][0]+4096*RATES[name][1]
            if row['status']!='reserved' or charge!=reserve or row['reservation_nano_usd']!=reserve:
                raise ValueError('Uncertain historical calls must retain their full reservation')
        totals[name]+=charge
    if totals!=source['cumulative_debit_nano_usd']:raise ValueError('Prior cumulative cost was reset')
    return totals


class ContinuationBudget:
    def __init__(self,path,policy,plan,configs,floor):
        if (any(type(v) is not int or v<0 for v in floor.values())
                or policy.get('schema_version')!='baseline-extension-budget-v0.1'
                or policy.get('plan_id')!=plan['plan_id'] or set(floor)!=set(MODELS)
                or policy.get('cap_nano_usd')!={p:2_000_000_000 for p in MODELS}
                or policy.get('safety_margin_nano_usd')!=100_000_000
                or policy.get('per_trial_cap_nano_usd')!=500_000_000
                or policy.get('max_new_uncertain_per_model')!=4):
            raise ValueError('Budget differs from the delegated cumulative limits')
        for name,cfg in configs.items():
            if (cfg['model']!=MODELS[name] or cfg['base_url']!=ENDPOINTS[name]
                    or cfg.get('max_tokens')!=4096 or cfg.get('max_request_bytes')!=131072 or cfg.get('extra_body')!={}):
                raise ValueError('Unpriced/changed model or request limit')
        if set(configs)!=set(MODELS):raise ValueError('Both fixed models are required')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.policy=policy;self.floor=floor
        self.binding={'plan_id':plan['plan_id'],'policy_sha256':digest(policy),'models_sha256':digest(configs)}
        self.allowed={c['trial_id']:c['profile'] for c in plan['trials'] if c['repeat']>0}
        with self.state() as state:
            if not state:state.update(schema_version='baseline-extension-ledger-v0.1',binding=self.binding,
              policy=policy,carried_forward_debit_nano_usd=floor,requests=[],stop_reason=None)

    @contextmanager
    def state(self):
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            state=read_json(self.path) if self.path.exists() else {}
            if state and (state.get('binding')!=self.binding or state.get('policy')!=self.policy
                          or state.get('carried_forward_debit_nano_usd')!=self.floor):
                raise ValueError('Spend state/identity changed')
            yield state
            save_json(self.path,state)

    def wrap(self,completion,profile,trial_id):
        if self.allowed.get(trial_id)!=profile:raise ValueError('Unplanned trial/model')
        inp,out=RATES[profile];reserve=135168*inp+4096*out
        def guarded(messages,remaining):
            request_id=uuid.uuid4().hex;reason=None
            with self.state() as state:
                rows=[r for r in state['requests'] if r['profile']==profile]
                used=self.floor[profile]+sum(r['debit_nano_usd'] for r in rows)
                trial_used=sum(r['debit_nano_usd'] for r in rows if r['trial_id']==trial_id)
                if any(r['status']=='in_flight' for r in state['requests']):reason='in_flight_request_requires_review'
                elif state['stop_reason']:reason=state['stop_reason']
                elif sum(r['status']=='uncertain_retained' for r in rows)>=4:reason='uncertain_request_limit'
                elif used+reserve>1_900_000_000 or trial_used+reserve>500_000_000:reason='spend_cap_before_request'
                if reason:state['stop_reason']=reason
                else:state['requests'].append(dict(request_id=request_id,profile=profile,trial_id=trial_id,
                    status='in_flight',reservation_nano_usd=reserve,debit_nano_usd=reserve))
            if reason:raise ModelError('Extension stopped before paid request: '+reason)
            error=None
            try:answer=completion(messages,remaining)
            except ModelError as exc:error=exc;answer=exc.diagnostics if isinstance(exc.diagnostics,dict) else {}
            usage=answer.get('usage') or {};incoming=usage.get('prompt_tokens');outgoing=usage.get('completion_tokens')
            identity_ok=answer.get('model_returned')==MODELS[profile]
            known=(identity_ok and type(incoming) is int and type(outgoing) is int
                   and 0<=incoming<=135168 and 0<=outgoing<=4096)
            with self.state() as state:
                row=next(r for r in state['requests'] if r['request_id']==request_id)
                if known:row.update(status='settled',prompt_tokens=incoming,completion_tokens=outgoing,
                    model_returned=answer['model_returned'],debit_nano_usd=incoming*inp+outgoing*out,
                    response_outcome='model_error_with_known_usage' if error else 'usable_text')
                else:
                    row.update(status='uncertain_retained',reason=str(error) if error else 'usage_or_identity_not_verified')
                    if answer.get('model_returned') and not identity_ok:state['stop_reason']='changed_model_identity'
                if error and any('API HTTP '+code in str(error) for code in ('401','402','403','404')):
                    state['stop_reason']='provider_access_or_credit_error'
            if error:raise error
            if not known:raise ModelError('Extension response has uncertain usage/identity; full reservation retained')
            return answer
        return guarded

    def stopped(self):
        return read_json(self.path).get('stop_reason')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();load_env(args.env_file)
    plan=make_plan(CONFIG);decision=read_json(DECISION);new=validate_plan(plan,decision)
    legacy=verify_legacy(plan,decision);floor=prior_floor(decision['budget'])
    configs=prepare_models(plan)
    for profile,cfg in configs.items():cfg['provenance']=model_provenance(cfg)
    image_id=DockerSandbox('overeager-sandbox:c04-v02')._docker(['image','inspect','--format','{{.Id}}','overeager-sandbox:c04-v02']).strip()
    if image_id!=decision['image_id']:raise ValueError('Image differs from archived baseline')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,text=True).strip():
        raise ValueError('Commit the checked implementation and protocol before paid execution')
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False)
    budget=ContinuationBudget(out/'spend-ledger.json',decision['budget'],plan,configs,floor)
    queues={p:[c for c in new if c['profile']==p] for p in MODELS}
    order=[queues[p][i] for i in range(27) for p in MODELS]
    frozen={str(p.relative_to(ROOT)):file_sha(p) for p in [CONFIG,DECISION,Path(__file__),ROOT/'docs/experiments/20261104-d0-30-each-protocol.md']}
    code=implementation_hash()
    manifest=dict(schema_version='baseline-extension-manifest-v0.1',recorded_at_utc=datetime.now(timezone.utc).isoformat(),
      git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),implementation_sha256=code,
      runner_file_sha256=frozen,plan=plan,models=configs,image_id=image_id,decision=decision,legacy_references=legacy,
      new_execution_order=[c['trial_id'] for c in order],new_trials=54,total_target=60)
    save_json(out/'frozen-manifest.json',manifest)
    receipt=dict(status='running',started_at_utc=datetime.now(timezone.utc).isoformat(),trials=[],stop_reason=None)
    save_json(out/'execution-receipt.json',receipt)
    try:
        for cell in order:
            if implementation_hash()!=code or any(file_sha(ROOT/n)!=h for n,h in frozen.items()):raise ValueError('Frozen files changed')
            if scenario_fingerprint(Path(cell['scenario']))!=cell['fingerprint']:raise ValueError('Scenario changed')
            profile=cell['profile'];folder=out/'trials'/cell['trial_id'];folder.mkdir(parents=True,exist_ok=False)
            completion=budget.wrap(make_completion(configs[profile]),profile,cell['trial_id'])
            try:
                report=run(cell['scenario'],folder/'attempt-0',completion,'llm',image_id,24,300,
                  inference_metadata(configs[profile],profile),'D0',read_json(cell['policy_path']),
                  approval_mode='scope_simulated',prompt_variant='environment-v2')
            except Exception as exc:
                report=read_json(folder/'attempt-0/report.json') if (folder/'attempt-0/report.json').exists() else {'status':'setup_error','trial_valid':False,'observation_valid':False}
                report.update(controller_error_type=type(exc).__name__)
            report.update(cell=cell,evidence_type='llm',defense_label='D0',attempts=[{'attempt':0,'status':report['status']}],selected_attempt=0)
            save_json(folder/'result.json',report)
            calls=[r for r in read_json(out/'spend-ledger.json')['requests'] if r['trial_id']==cell['trial_id']]
            row={k:report.get(k) for k in ('status','trial_valid','observation_valid','task_success','out_of_scope_observed')}
            row.update(trial_id=cell['trial_id'],profile=profile,scenario_id=cell['scenario_id'],repeat=cell['repeat'],paid_requests=len(calls))
            receipt['trials'].append(row);save_json(out/'execution-receipt.json',receipt);print(json.dumps(row),flush=True)
            if budget.stopped() or report['status'] in ('cleanup_error','error','tool_error','setup_error'):
                receipt.update(status='stopped',stop_reason=budget.stopped() or report['status']);break
        else:receipt['status']='completed_54_new_plus_6_archived'
    except Exception as exc:
        receipt.update(status='stopped',stop_reason=type(exc).__name__);raise
    finally:
        receipt['finished_at_utc']=datetime.now(timezone.utc).isoformat();save_json(out/'execution-receipt.json',receipt)
    return 0 if receipt['status']=='completed_54_new_plus_6_archived' else 2


if __name__=='__main__':raise SystemExit(main())
