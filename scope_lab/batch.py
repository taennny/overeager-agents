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
from .defenses import validate_policy, defense_label
from .sandbox import DockerSandbox
from .provenance import implementation_hash

PROFILES = {'gpt','claude','exaone','qwen','solar','mock-compliant','mock-overeager','mock-no_action'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scenario_fingerprint(source, mock=False):
    scenario, spec, evaluator = load_scenario(source)
    policies = {p.name: validate_policy(read_json(p)) for p in sorted(source.parent.glob('policy*.json'))}
    value = {'scenario': read_json(source), 'scope': spec, 'policies': policies,
                   'fixture': snapshot(scenario['fixture'])['entries'], 'evaluator': evaluator,
                   'action_scope': scenario.get('action_scope_spec'), 'test_tool': scenario.get('test_config'),
                   'control': read_json(source.parent/'control.json') if mock else None}
    if scenario.get('schema_version') == 'scenario-v0.3':
        value.update(risk=scenario['risk_spec'], observations=scenario['observation_spec'], design=scenario['design_spec'])
    return digest(value)


def make_plan(config_path):
    path = Path(config_path).resolve()
    config = read_json(path)
    if config.get('schema_version') == 'batch-v0.5':
        from .design_v05 import make_plan_v05
        return make_plan_v05(path, config)
    fields = {'schema_version','profiles','scenarios','defenses','repeats','seed','max_steps','timeout_seconds','max_retries','orr_eligible'}
    commercial = config.get('schema_version') == 'batch-v0.4-api'
    v4 = config.get('schema_version') in ('batch-v0.3', 'batch-v0.4-api')
    new = config.get('schema_version') in ('batch-v0.2', 'batch-v0.3', 'batch-v0.4-api')
    if v4:
        fields.add('prompt_variant')
    if new:
        fields |= {'policy_variants', 'approval_mode', 'inference'}
    if set(config) != fields or config['schema_version'] not in ('batch-v0.1', 'batch-v0.2', 'batch-v0.3', 'batch-v0.4-api'):
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
    if new and not v4 and (config['policy_variants'] != ['narrow', 'fit', 'wide'] or
                config['approval_mode'] != 'scope_simulated' or 'D1' in config['defenses'] or
                config['inference'] != {'protocol': 'ollama', 'output_format': 'json'}):
        raise ValueError('v0.3 pilot requires three reviewed policies, scope simulation and Ollama JSON; D1 is not frozen')
    if v4 and not commercial:
        if (config['policy_variants'] != ['narrow', 'fit', 'wide'] or
                config['approval_mode'] != 'scope_simulated' or
                config['prompt_variant'] != 'environment-v1' or
                config['inference'] != {'protocol': 'ollama', 'output_format': 'json',
                                        'num_ctx': 8192, 'max_tokens': 4096}):
            raise ValueError('Invalid v0.4 compatibility-pilot contract')
    if commercial:
        if (config['profiles'] != ['claude', 'gpt'] or
                config['policy_variants'] != ['narrow', 'fit', 'wide'] or
                config['approval_mode'] != 'scope_simulated' or
                config['prompt_variant'] != 'environment-v1' or config['max_retries'] != 0 or
                config['max_steps'] > 24 or config['timeout_seconds'] > 300 or
                config['inference'] != {'protocol': 'provider-native', 'max_tokens': 4096,
                                        'sampling': 'provider-default', 'max_request_bytes': 131072}):
            raise ValueError('Invalid Claude/GPT pilot contract')
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
                for variant in ([None] if defense == 'D0' or (v4 and defense == 'D1') else policies):
                    for repeat in range(config['repeats']):
                        cell={'scenario':str(source),'scenario_id':pair[0],'language':pair[1],
                              'profile':profile,'defense':defense,'repeat':repeat,'fingerprint':fingerprint,
                              'orr_eligible':config['orr_eligible']}
                        if new:
                            cell.update(policy_variant=variant or 'none',
                                        policy_path=str(source.parent/('policy.'+(variant or 'fit')+'.json')),
                                        approval_mode=config['approval_mode'])
                        if v4:
                            cell['prompt_variant'] = config['prompt_variant']
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


def prepare_models(plan):
    """Validate credentials and inference without any network or Docker calls."""
    configs = {p: profile_config(p) for p in plan['config']['profiles'] if not p.startswith('mock-')}
    schema = plan['config']['schema_version']
    if schema in ('batch-v0.4-api', 'batch-v0.5'):
        expected = {'gpt': ('openai', 'https://api.openai.com/v1'),
                    'claude': ('anthropic', 'https://api.anthropic.com/v1')}
        for profile, config in configs.items():
            protocol, endpoint = expected[profile]
            if (config.get('protocol', 'openai'), config['base_url']) != (protocol, endpoint):
                raise ValueError('API pilot requires the official provider endpoint: ' + profile)
            config.update({k: plan['config']['inference'][k] for k in
                           ('max_tokens', 'max_request_bytes', 'sampling')})
    if schema == 'batch-v0.3':
        for config in configs.values():
            config.update({k: plan['config']['inference'][k] for k in ('num_ctx', 'max_tokens')})
    if schema in ('batch-v0.2', 'batch-v0.3'):
        for config in configs.values():
            if any(config.get(k) != v for k, v in plan['config']['inference'].items()):
                raise ValueError('Model environment does not match planned Ollama JSON configuration')
    return configs


def validate_api_preflight(plan, folder, configs, image_id, implementation):
    """Recheck original evidence, not an editable ready flag, before paid expansion."""
    from .readiness import review
    if not folder:
        raise ValueError('API defense comparison requires --preflight with completed six-trial D0 evidence')
    folder = Path(folder)
    lock = read_json(folder/'plan.json')
    v05 = plan['config']['schema_version'] == 'batch-v0.5'
    expected = make_plan(Path(__file__).resolve().parents[1]/('experiments/v05-preflight.json' if v05 else 'experiments/api-preflight.json'))
    candidate = dict(plan['config'], defenses=['D0'])
    if v05:
        candidate.update(experiment_id=expected['config']['experiment_id'], policy_variants=['fit'])
    if (lock['plan'] != expected or candidate != expected['config'] or
            lock['models'] != configs or lock['image_id'] != image_id or
            lock['implementation_hash'] != implementation):
        raise ValueError('Preflight code/assets/model/settings/image differ; run a new preflight')
    if review(folder)['compatibility_gate'] != 'ready_for_team_review':
        raise ValueError('Preflight results are incomplete or failed; review before expansion')


def execute_plan(plan, output, live=False, limit=20, image='overeager-sandbox:week1', profile_filter=None, preflight=None, design_review=None):
    if type(limit) is not int or limit < 1:
        raise ValueError('Positive per-invocation run limit required')
    if profile_filter is not None and profile_filter not in plan['config']['profiles']:
        raise ValueError('Profile filter is not in plan')
    real=any(not c['profile'].startswith('mock-') for c in plan['trials'])
    if real and not live:
        raise ValueError('Live API calls require --live; planning makes no API requests')
    api_contract = plan['config']['schema_version'] in ('batch-v0.4-api', 'batch-v0.5') and real
    if api_contract and (limit != 1 or profile_filter is None):
        raise ValueError('API pilot runs one trial at a time: specify --profile and --limit 1')
    decision = None
    if real and plan['config']['schema_version'] == 'batch-v0.5':
        from .design_v05 import verify_design_review
        decision = verify_design_review(plan, design_review)
    configs = prepare_models(plan)
    for config in configs.values():
        config['provenance'] = model_provenance(config)
    for cell in plan['trials']:
        if scenario_fingerprint(Path(cell['scenario']), any(p.startswith('mock-') for p in plan['config']['profiles'])) != cell['fingerprint']:
            raise ValueError('Scenario assets changed after planning; make a new plan')
    # Keys are never serialized; profile config contains only key ENVIRONMENT NAMES.
    image_id=DockerSandbox(image)._docker(['image','inspect','--format','{{.Id}}',image]).strip()
    implementation=implementation_hash()
    if api_contract and any(c['defense'] != 'D0' for c in plan['trials']):
        validate_api_preflight(plan, preflight, configs, image_id, implementation)
    lock={'plan':plan,'models':configs,'image_id':image_id,'implementation_hash':implementation}
    if decision is not None:
        lock['design_review'] = decision
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
                                   approval_mode=cell.get('approval_mode','recorded_or_deny'),
                                   prompt_variant=cell.get('prompt_variant','baseline'))
                    except Exception as exc:
                        report=read_json(target/'report.json') if (target/'report.json').exists() else {'status':'setup_error','retryable':False}
                        # A failed execution does not erase successfully collected FS evidence.
                        report.update(trial_valid=False,error_type=type(exc).__name__)
                        report.setdefault('observation_valid', False)
                    save_json(target/'attempt-result.json',report)
                attempts.append({'attempt':attempt,'status':report['status'],'trial_valid':report.get('trial_valid',False)})
                if report.get('trial_valid') or not report.get('retryable'):
                    break
                if attempt < plan['config']['max_retries']:
                    time.sleep(1)
            report.update(cell=cell,attempts=attempts,selected_attempt=attempt,
                          defense_label=defense_label(cell['defense'], approval_mode=cell.get('approval_mode', 'recorded_or_deny')),
                          evidence_type='scripted_control_not_llm' if cell['profile'].startswith('mock-') else 'llm')
            save_json(summary,report)
            executed+=1
            print(json.dumps({'trial_id':cell['trial_id'],'status':report['status'],'defense':defense_label(cell['defense'], approval_mode=cell.get('approval_mode', 'recorded_or_deny'))}),flush=True)
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
    parser.add_argument('--preflight', help='Completed API D0 preflight folder, required for API defense comparisons')
    parser.add_argument('--design-review', help='Actual A/B design decision bound to the v0.5 assets; no inferred approval')
    args=parser.parse_args()
    try:
        plan=make_plan(args.config)
        if args.command=='plan':
            out=Path(args.out)
            if out.exists(): raise ValueError('Plan output already exists')
            save_json(out,plan);print(json.dumps({'planned':len(plan['trials']),'plan_id':plan['plan_id']}))
        else:
            print(json.dumps(execute_plan(plan,args.out,args.live,args.limit,args.image,profile_filter=args.profile,preflight=args.preflight,design_review=args.design_review)))
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print(json.dumps({'status':'error','error':str(exc)}));return 2

if __name__=='__main__':
    raise SystemExit(main())
