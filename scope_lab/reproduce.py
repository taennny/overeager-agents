"""API-free reproduction package. Actor identity is self-reported, never inferred."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from .batch import make_plan, execute_plan
from .cli import save_json
from .provenance import implementation_hash
from .sandbox import DockerSandbox
from .validate_controls import validate


def _reproduce(output, actor, image):
    root = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    def command(args):
        return subprocess.check_output(args, cwd=root, text=True).strip()
    evidence = {'schema_version': 'reproduction-v0.1', 'actor_self_reported': actor,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'commit': command(['git','rev-parse','HEAD']),
                'tracked_worktree_dirty': bool(command(['git','status','--porcelain','--untracked-files=no'])),
                'implementation_sha256': implementation_hash(),
                'python': platform.python_version(), 'os': platform.system(),
                'machine': platform.machine(), 'api_requests': 0,
                'evidence_type': 'scripted_control_not_llm',
                'a_environment_run_claimed': actor == 'A',
                'actor_attestation_is_not_independent_identity_verification': True}
    box = DockerSandbox(image)
    evidence['image_id'] = box._docker(['image','inspect','--format','{{.Id}}',image]).strip()
    evidence['image_platform'] = box._docker(['image','inspect','--format','{{.Os}}/{{.Architecture}}',image]).strip()
    evidence['docker_version'] = box._docker(['version','--format','{{.Server.Version}}']).strip()
    evidence['dockerfile_sha256'] = hashlib.sha256((root/'docker/Dockerfile').read_bytes()).hexdigest()
    plans = {}
    for name in ('preflight','core','policy-width','controls'):
        plan = make_plan(root/('experiments/v05-' + name + '.json'))
        save_json(output/('plan-' + name + '.json'), plan)
        plans[name] = len(plan['trials'])
    evidence['offline_plan_counts'] = plans
    save_json(output/'evidence.json', dict(evidence, status='running'))
    env = dict(os.environ, SCOPE_DOCKER_TESTS='1', SCOPE_V03_IMAGE=image)
    with (output/'tests.log').open('w') as stream:
        tested = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],
                                cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    evidence['tests_exit_code'] = tested.returncode
    evidence['tests_log_sha256'] = hashlib.sha256((output/'tests.log').read_bytes()).hexdigest()
    if tested.returncode:
        save_json(output/'evidence.json', dict(evidence,status='failed_tests'))
        return 2
    plan = make_plan(root/'experiments/v05-controls.json')
    execute_plan(plan,output/'controls',image=image,limit=len(plan['trials']))
    result, metrics = validate(plan,output/'controls')
    save_json(output/'controls-validation.json', result)
    save_json(output/'controls-metrics.json', metrics)
    evidence.update(controls_planned=result['planned'],controls_passed=result['passed'],
                    assets={c['scenario_id']:c['fingerprint'] for c in plan['trials']},
                    status='passed' if result['all_passed'] else 'failed_controls')
    # A named actor is NOT proof that another person's machine was used.
    evidence['team_reproduction_complete'] = False
    save_json(output/'evidence.json',evidence)
    return 0 if result['all_passed'] else 2


def reproduce(output, actor, image):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new reproduction output directory')
    try:
        return _reproduce(output, actor, image)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # A timeout or cleanup failure must leave explicit failure evidence.
        output.mkdir(parents=True, exist_ok=True)
        path = output/'evidence.json'
        evidence = json.loads(path.read_text()) if path.exists() else {}
        evidence.update(status='failed_infrastructure', error_type=type(exc).__name__,
                        actor_self_reported=actor, api_requests=0,
                        team_reproduction_complete=False)
        save_json(path, evidence)
        return 2


def compare_evidence(first, second):
    left = json.loads(Path(first).read_text())
    right = json.loads(Path(second).read_text())
    fields = ('commit', 'implementation_sha256', 'image_id', 'image_platform',
              'dockerfile_sha256', 'assets', 'offline_plan_counts')
    differences = [k for k in fields if not left.get(k) or left.get(k) != right.get(k)]
    ready = all(r.get('status') == 'passed' and r.get('tests_exit_code') == 0 and
                r.get('controls_passed') == r.get('controls_planned') == 36 and
                r.get('tracked_worktree_dirty') is False for r in (left, right))
    roles = {left.get('actor_self_reported'), right.get('actor_self_reported')}
    return {'matching_technical_evidence': ready and not differences,
            'differences': differences, 'both_checks_passed_on_clean_commits': ready,
            'ab_roles_claimed': roles == {'A', 'B'},
            'team_reproduction_complete': False,
            'note': 'Matching files do not verify who ran them. A/B must attest the distinct environments; CI is not A.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out')
    parser.add_argument('--actor',choices=['A','B','CI'])
    parser.add_argument('--image',default='overeager-sandbox:v05')
    parser.add_argument('--compare',nargs=2,metavar=('B_EVIDENCE','A_EVIDENCE'))
    args=parser.parse_args()
    if args.compare:
        result=compare_evidence(*args.compare)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['matching_technical_evidence'] and result['ab_roles_claimed'] else 2
    if not args.out or not args.actor:
        parser.error('--out and --actor are required for an execution')
    return reproduce(args.out,args.actor,args.image)


if __name__=='__main__':raise SystemExit(main())
