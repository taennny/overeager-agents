"""Serial bounded batch runner with immutable plans and per-attempt evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time

from .cli import read_json, save_json
from .harness import load_scenario, run
from .model_client import chat, profile_config, ModelError
from .oracle import snapshot
from .defenses import validate_policy
from .sandbox import DockerSandbox

PROFILES = {'gpt','claude','exaone','qwen','solar','mock-compliant','mock-overeager','mock-no_action'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def make_plan(config_path):
    path = Path(config_path).resolve()
    config = read_json(path)
    fields = {'schema_version','profiles','scenarios','defenses','repeats','seed','max_steps','timeout_seconds','max_retries','orr_eligible'}
    if set(config) != fields or config['schema_version'] != 'batch-v0.1':
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
    trials, pairs = [], set()
    for source in config['scenarios']:
        source = (path.parent/source).resolve()
        scenario, spec, evaluator = load_scenario(source)
        policy = validate_policy(read_json(source.parent/'policy.json'))
        pair=(scenario['scenario_id'],scenario['language'])
        if pair in pairs:
            raise ValueError('Duplicate scenario/language pair')
        pairs.add(pair)
        fingerprint=digest({'scenario':read_json(source),'scope':spec,'policy':policy,
                            'fixture':snapshot(scenario['fixture'])['entries'],'evaluator':evaluator,
                            'control':read_json(source.parent/'control.json') if any(p.startswith('mock-') for p in config['profiles']) else None})
        for profile in config['profiles']:
            for defense in config['defenses']:
                for repeat in range(config['repeats']):
                    cell={'scenario':str(source),'scenario_id':pair[0],'language':pair[1],
                          'profile':profile,'defense':defense,'repeat':repeat,'fingerprint':fingerprint,
                          'orr_eligible':config['orr_eligible']}
                    cell['trial_id']=digest(cell)[:20]
                    trials.append(cell)
    random.Random(config['seed']).shuffle(trials)
    return {'config':config,'trials':trials,'plan_id':digest({'config':config,'trials':trials})}


def mock_completion(cell):
    control=read_json(Path(cell['scenario']).parent/'control.json')
    actions=[{'tool':'read_file','path':'solution.py'}]
    if cell['profile']!='mock-no_action':
        actions.append({'tool':'write_file','path':'solution.py','content':control['solution']})
    if cell['profile']=='mock-overeager':
        actions.append({'tool':'write_file','path':control['trap'],'content':'unsolicited synthetic change\n'})
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
    # Keys are never serialized; profile config contains only key ENVIRONMENT NAMES.
    image_id=DockerSandbox(image)._docker(['image','inspect','--format','{{.Id}}',image]).strip()
    implementation=digest({str(f.relative_to(Path(__file__).parent.parent)):hashlib.sha256(f.read_bytes()).hexdigest()
                           for folder in ('scope_lab','docker') for f in sorted((Path(__file__).parent.parent/folder).glob('*.py'))})
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
                        config=configs[profile]
                        def completion(messages,remaining):
                            return chat(config,messages,timeout=min(60,remaining),max_tokens=2048)
                    try:
                        report=run(cell['scenario'],target,completion,
                                   'scripted_control_not_llm' if is_mock else 'llm',image_id,
                                   plan['config']['max_steps'],plan['config']['timeout_seconds'],
                                   {'profile':profile,'model_requested':configs.get(profile,{}).get('model')},
                                   cell['defense'],read_json(Path(cell['scenario']).parent/'policy.json'))
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
    args=parser.parse_args()
    try:
        plan=make_plan(args.config)
        if args.command=='plan':
            out=Path(args.out)
            if out.exists(): raise ValueError('Plan output already exists')
            save_json(out,plan);print(json.dumps({'planned':len(plan['trials']),'plan_id':plan['plan_id']}))
        else:
            print(json.dumps(execute_plan(plan,args.out,args.live,args.limit,profile_filter=args.profile)))
        return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print(json.dumps({'status':'error','error':str(exc)}));return 2

if __name__=='__main__':
    raise SystemExit(main())
