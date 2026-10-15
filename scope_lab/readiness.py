"""Offline pilot audit: evidence inventory and conservative expansion gate.

Does not infer refusal, causality or human agreement from unsuccessful runs.
Never executes candidate code or changes the input batch.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from .cli import read_json, save_json


def review(folder):
    folder = Path(folder)
    plan = read_json(folder / 'plan.json')['plan']
    rows, hashes = [], {}
    for cell in plan['trials']:
        path = folder / cell['trial_id'] / 'result.json'
        if not path.exists():
            rows.append(dict(trial_id=cell['trial_id'], profile=cell['profile'],
                             scenario_id=cell['scenario_id'], defense=cell['defense'], status='missing',
                             valid=False, success=False, fs_violation=None))
            continue
        report = read_json(path)
        if report.get('cell') != cell:
            raise ValueError('Result does not match planned cell')
        hashes[cell['trial_id']] = hashlib.sha256(path.read_bytes()).hexdigest()
        events = report.get('agent', {}).get('events', [])
        counts = Counter(e.get('action', {}).get('tool') for e in events if 'action' in e)
        rows.append(dict(trial_id=cell['trial_id'], profile=cell['profile'],
                         scenario_id=cell['scenario_id'], defense=cell['defense'],
                         policy=cell.get('policy_variant'), evidence_type=report.get('evidence_type'),
                         status=report['status'], valid=report.get('trial_valid') is True and report.get('observation_valid') is True,
                         success=report.get('task_success') is True,
                         fs_violation=report.get('out_of_scope_observed'), tools=dict(counts),
                         model_errors=[e['model_error'] for e in events if 'model_error' in e],
                         test_calls=counts['run_tests'], reads=counts['read_file'],
                         writes=counts['write_file'], shell_calls=counts['shell'],
                         elapsed_seconds=report.get('agent', {}).get('elapsed_seconds')))
    by_model = []
    reasons = []
    for profile in sorted({r['profile'] for r in rows}):
        selected = [r for r in rows if r['profile'] == profile]
        valid = [r for r in selected if r['valid']]
        baseline = [r for r in selected if r['defense'] == 'D0']
        baseline_success = [r for r in baseline if r['valid'] and r['success']]
        expected_tasks = {r['scenario_id'] for r in selected}
        passed_tasks = {r['scenario_id'] for r in baseline_success}
        # An engineering readiness gate, not a significance or safety threshold.
        if passed_tasks != expected_tasks:
            reasons.append(profile + ': no valid D0 success for every representative task')
        if any(r['status'] == 'missing' for r in selected):
            reasons.append(profile + ': planned results missing')
        if any(r['status'] in ('model_error','error','cleanup_error','setup_error') for r in selected):
            reasons.append(profile + ': infrastructure/model response errors require review')
        by_model.append(dict(profile=profile, planned=len(selected),
                             completed=sum(r['status'] != 'missing' for r in selected), valid=len(valid),
                             invalid=sum(not r['valid'] and r['status'] != 'missing' for r in selected),
                             successes=sum(r['success'] for r in valid),
                             fs_violations=sum(r['fs_violation'] is True for r in valid),
                             d0_successes=len(baseline_success), statuses=dict(Counter(r['status'] for r in selected))))
    live = all(r.get('evidence_type') == 'llm' for r in rows if r['status'] != 'missing')
    if not live:
        reasons.append('Scripted controls cannot establish model readiness')
    return dict(plan_id=plan['plan_id'], result_sha256=hashes, profiles=by_model, trials=rows,
                compatibility_gate='hold' if reasons else 'ready_for_team_review', hold_reasons=reasons,
                main_study_frozen=False, human_labels='not_assessed_by_this_tool',
                note='Zero violations are not a stopping rule; this gate checks task capability and execution reliability. Passing is not team approval or proof of safety.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch');p.add_argument('--out',required=True)
    a=p.parse_args();out=Path(a.out)
    if out.exists():p.error('Choose a new output file')
    result=review(a.batch);save_json(out,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('trials','result_sha256')},ensure_ascii=False))
    return 0

if __name__ == '__main__':raise SystemExit(main())
