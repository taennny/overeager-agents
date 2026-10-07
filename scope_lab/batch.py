"""Serial bounded batch runner with immutable plans and per-attempt evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time

from .cli import read_json, save_json
from .harness import load_scenario, run
from .model_client import profile_config, ModelError, make_completion, inference_metadata, model_provenance
from .oracle import snapshot
from .defenses import validate_policy
from .sandbox import DockerSandbox
from .provenance import implementation_hash

PROFILES = {'gpt','claude','exaone','qwen','solar','mock-compliant','mock-overeager','mock-no_action'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scenario_fingerprint(source, mock=False):
    scenario, spec, evaluator = load_scenario(source)
    policies = {p.name: validate_policy(read_json(p)) for p in sorted(source.parent.glob('policy*.json'))}
    return digest({'scenario': read_json(source), 'scope': spec, 'policies': policies,
                   'fixture': snapshot(scenario['fixture'])['entries'], 'evaluator': evaluator,
                   'action_scope': scenario.get('action_scope_spec'), 'test_tool': scenario.get('test_config'),
                   'control': read_json(source.parent/'control.json') if mock else None})


def make_plan(config_path):
    path = Path(config_path).resolve()
    config = read_json(path)
    fields = {'schema_version','profiles','scenarios','defenses','repeats','seed','max_steps','timeout_seconds','max_retries','orr_eligible'}
    new = config.get('schema_version') == 'batch-v0.2'
    if new:
        fields |= {'policy_variants', 'approval_mode', 'inference'}
    if set(config) != fields or config['schema_version'] not in ('batch-v0.1', 'batch-v0.2'):
        raise ValueError('Invalid batch configuration fields')
    for key in ('profiles','scenarios','defenses'):
        if not isinstance(config[key], list) or not config[key] or any(not isinstance(x,str) for x in config[key]) or len(set(config[key]))!=len(config[key]):
            raise ValueError('Expected nonempty unique lists')
    if not set(config['profiles']) <= PROFILES or not set(config['defenses']) <= {'D0','D1','D2','D3'}:
        raise ValueError('Unknown profile or defense')
    for key in ('repeats','max_steps','timeout_seconds'):
        if type(config[key]) is not int or not 1 <= config[key] <= 10000:
            raise ValueError('Invalid positive budget: '+key)
    if type(config['max_retries']) is not int or not 0 <= config['max_retries'] <= 2 or type(config['seed']) is not int or type(config['orr_eligible']) is not bool:
        raise ValueError('Invalid retry, seed or eligibility')
    if new and (config['policy_variants'] != ['narrow', 'fit', 'wide'] or
                config['approval_mode'] != 'scope_simulated' or 'D1' in config['defenses'] or
                config['inference'] != {'protocol': 'ollama', 'output_format': 'json'}):
        raise ValueError('v0.3 pilot requires three reviewed policies, scope simulation and Ollama JSON; D1 is not frozen')
    trials, pairs = [], set()
    for source in config['scenarios']:
        source = (path.parent/source).resolve()
        scenario, spec, evaluator = load_scenario(source)
        if new and scenario['schema_version'] != 'scenario-v0.2':
            raise ValueError('New batch requires fixed-test and action-scope assets')
        policies = ['narrow', 'fit', 'wide'] if new else [None]
        for variant in policies:
            validate_policy(read_json(source.parent/('policy.'+variant+'.json' if variant else 'policy.json')))
        pair=(scenario['scenario_id'],scenario['language'])
        if pair in pairs:
            raise ValueError('Duplicate scenario/language pair')
        pairs.add(pair)
        fingerprint = scenario_fingerprint(source, any(p.startswith('mock-') for p in config['profiles']))
        for profile in config['profiles']:
            for defense in config['defenses']:
                for variant in ([None] if defense == 'D0' else policies):
                    for repeat in range(config['repeats']):
                        cell={'scenario':str(source),'scenario_id':pair[0],'language':pair[1],
                              'profile':profile,'defense':defense,'repeat':repeat,'fingerprint':fingerprint,
                              'orr_eligible':config['orr_eligible']}
                        if new:
                            cell.update(policy_variant=variant or 'none',
                                        policy_path=str(source.parent/('policy.'+(variant or 'fit')+'.json')),
                                        approval_mode=config['approval_mode'])
                        cell['trial_id']=digest(cell)[:20]
                        trials.append(cell)
    random.Random(config['seed']).shuffle(trials)
    return {'config':config,'trials':trials,'plan_id':digest({'config':config,'trials':trials})}


def mock_completion(cell):
    control=read_json(Path(cell['scenario']).parent/'control.json')
    if control.get('version') == 'coding-controls-v0.1':
        actions = []
        for path, content in control['solutions'].items():
            actions.append({'tool': 'read_file', 'path': path})
            if cell['profile'] != 'mock-no_action':
                actions.append({'tool': 'write_file', 'path': path, 'content': content})
        actions.append({'tool': 'run_tests'})
    else:
        actions=[{'tool':'read_file','path':'solution.py'}]
        if cell['profile']!='mock-no_action':
            actions.append({'tool':'write_file','path':'solution.py','content':control['solution']})
    if cell['profile']=='mock-overeager':
        actions.append({'tool':'write_file','path':control['trap'],'content':control.get('trap_content','unsolicited synthetic change\n')})
    actions.append({'tool':'finish','message':'scripted control'})
    iterator=iter(actions)
    def completion(messages, remaining):
        return {'content':json.dumps(next(iterator)),'usage':{},'is_mock':True}
    return completion


def execute_plan(plan, output, live=False, limit=20, image='overeager-sandbox:week1', profile_filter=None):
    if type(limit) is not int or limit < 1:
        raise ValueError('Positive per-invocation run limit required')
    if profile_filter is not None and profile_filter not in plan['config']['profiles']:
        raise ValueError('Profile filter is not in plan')
    real=any(not c['profile'].startswith('mock-') for c in plan['trials'])
    if real and not live:
        raise ValueError('Live API calls require --live; planning makes no API requests')
    configs={p:profile_config(p) for p in plan['config']['profiles'] if not p.startswith('mock-')}
    if plan['config']['schema_version'] == 'batch-v0.2':
        for config in configs.values():
            if any(config.get(k) != v for k, v in plan['config']['inference'].items()):
                raise ValueError('Model environment does not match planned Ollama JSON configuration')
    for config in configs.values():
        config['provenance'] = model_provenance(config)
    for cell in plan['trials']:
        if scenario_fingerprint(Path(cell['scenario']), any(p.startswith('mock-') for p in plan['config']['profiles'])) != cell['fingerprint']:
            raise ValueError('Scenario assets changed after planning; make a new plan')
    # Keys are never serialized; profile config contains only key ENVIRONMENT NAMES.
    image_id=DockerSandbox(image)._docker(['image','inspect','--format','{{.Id}}',image]).strip()
    implementation=implementation_hash()
    lock={'plan':plan,'models':configs,'image_id':image_id,'implementation_hash':implementation}
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    lockfile=output/'plan.json'
    lockpath=output/'.running'
    with lockpath.open('x') as handle:
        handle.write('Active runner. Remove only after confirming no runner remains.\n')
    executed=0
    try:
        if lockfile.exists():
            if read_json(lockfile)!=lock:
                raise ValueError('Plan/model/image/code changed; use a new output directory')
        else:
            if any(p.name!='.running' for p in output.iterdir()):
                raise ValueError('Nonempty output without a plan')
            save_json(lockfile,lock)
        for cell in plan['trials']:
            if profile_filter is not None and cell['profile'] != profile_filter:
                continue
            folder=output/cell['trial_id']; summary=folder/'result.json'
            if summary.exists():
                continue
            if executed >= limit:
                break
            if implementation_hash() != implementation:
                raise ValueError('Implementation changed during the batch; stop and use a new output')
            if cell['profile'] in configs:
                config = configs[cell['profile']]
                if model_provenance(config) != config['provenance']:
                    raise ValueError('Model identity/runtime changed during the batch; stop and use a new output')
            if scenario_fingerprint(Path(cell['scenario']), any(p.startswith('mock-') for p in plan['config']['profiles'])) != cell['fingerprint']:
                raise ValueError('Scenario assets changed during execution; stop and make a new plan')
            folder.mkdir(exist_ok=True)
            attempts=[]
            for attempt in range(plan['config']['max_retries']+1):
                target=folder/('attempt-'+str(attempt))
                if target.exists():
                    # Crash recovery never silently reruns a possibly paid request.
                    if not (target/'attempt-result.json').exists():
                        raise ValueError('Interrupted attempt requires manual review: '+str(target))
                    report=read_json(target/'attempt-result.json')
                else:
                    profile=cell['profile']; is_mock=profile.startswith('mock-')
                    if is_mock:
                        completion=mock_completion(cell)
                    else:
                        completion=make_completion(configs[profile])
                    try:
                        report=run(cell['scenario'],target,completion,
                                   'scripted_control_not_llm' if is_mock else 'llm',image_id,
                                   plan['config']['max_steps'],plan['config']['timeout_seconds'],
                                   {'profile':profile} if is_mock else inference_metadata(configs[profile],profile),
                                   cell['defense'],read_json(cell.get('policy_path',str(Path(cell['scenario']).parent/'policy.json'))),
                                   approval_mode=cell.get('approval_mode','recorded_or_deny'))
                    except Exception as exc:
                        report=read_json(target/'report.json') if (target/'report.json').exists() else {'status':'setup_error','retryable':False}
                        report.update(trial_valid=False,observation_valid=False,error_type=type(exc).__name__)
                    save_json(target/'attempt-result.json',report)
                attempts.append({'attempt':attempt,'status':report['status'],'trial_valid':report.get('trial_valid',False)})
                if report.get('trial_valid') or not report.get('retryable'):
                    break
                if attempt < plan['config']['max_retries']:
                    time.sleep(1)
            report.update(cell=cell,attempts=attempts,selected_attempt=attempt,
                          evidence_type='scripted_control_not_llm' if cell['profile'].startswith('mock-') else 'llm')
            save_json(summary,report)
            executed+=1
            print(json.dumps({'trial_id':cell['trial_id'],'status':report['status'],'defense':cell['defense']}),flush=True)
            if report['status']=='cleanup_error':
                raise ValueError('Stop batch: cleanup failure requires operator review')
    finally:
        lockpath.unlink()
    return {'executed_this_invocation':executed,'planned':len(plan['trials']),
            'completed':sum((output/c['trial_id']/'result.json').exists() for c in plan['trials'])}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['plan','run'])
    parser.add_argument('--config',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--live',action='store_true');parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--profile', help='Run only this planned model; use for sequential one-GPU serving')
    parser.add_argument('--image', default='overeager-sandbox:week1')
    args=parser.parse_args()
    try:
        plan=make_plan(args.config)
        if args.command=='plan':
            out=Path(args.out)
            if out.exists(): raise ValueError('Plan output already exists')
            save_json(out,plan);print(json.dumps({'planned':len(plan['trials']),'plan_id':plan['plan_id']}))
        else:
            print(json.dumps(execute_plan(plan,args.out,args.live,args.limit,args.image,profile_filter=args.profile)))
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print(json.dumps({'status':'error','error':str(exc)}));return 2

if __name__=='__main__':
    raise SystemExit(main())
