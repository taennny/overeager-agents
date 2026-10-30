"""Export complete redacted comparison evidence, grouped by model/task.

Keep source file hashes and all artifact bytes; create separate per-cell notes.
"""
import argparse
import base64
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import shlex

from scope_lab.cli import save_json

ROOT=Path.cwd()
TASK={'v05-log-mask':('T1','로그 마스킹'),'v05-csv-roundtrip':('T2','CSV 왕복'),'v05-dev-config':('T3','개발 설정')}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',required=True);p.add_argument('--redact-env-file',required=True)
    args=p.parse_args();source=Path(args.session).resolve()
    dest=ROOT/'docs/evidence/defense-comparison/live';notes=ROOT/'docs/experiments/defense-comparison-20261030'
    if dest.exists() or notes.exists():raise ValueError('Never overwrite published comparison evidence')
    secrets=[]
    for line in Path(args.redact_env_file).read_text().splitlines():
        name,sep,value=line.partition('=')
        if sep and name.strip().removeprefix('export ') in {'OPENAI_API_KEY','ANTHROPIC_API_KEY'}:secrets.extend(shlex.split(value,comments=True))
    def clean(text):
        for secret in secrets:
            if secret:text=text.replace(secret,'[REDACTED]')
        return text.replace(str(ROOT),'[REPO]').replace(str(Path.home()),'[HOME]').replace('/private/tmp','[TMP]')
    dest.mkdir(parents=True);notes.mkdir();inventory=[]
    def record(path):
        if path.is_symlink() or not path.is_file():raise ValueError('Unexpected nonregular source artifact')
        raw=path.read_bytes()
        try:text=clean(raw.decode('utf-8'));encoding='utf-8';published=text.encode()
        except UnicodeDecodeError:text=base64.b64encode(raw).decode('ascii');encoding='base64';published=raw
        return dict(source_path=str(path.relative_to(source)),source_sha256=sha(raw),published_content_sha256=sha(published),encoding=encoding,content=text)
    for path in sorted(source.glob('*.json')):
        item=record(path);target=dest/path.name;target.write_text(item.pop('content'))
        item['published_file']=str(target.relative_to(ROOT));inventory.append(item)
    for phase in ('preflight','core'):
        planfile=source/phase/'plan.json'
        if planfile.exists():
            item=record(planfile);target=dest/(phase+'-plan.json');target.write_text(item.pop('content'))
            item['published_file']=str(target.relative_to(ROOT));inventory.append(item)
    receipt=json.loads((source/'execution-receipt.json').read_text())
    manifest=json.loads((source/'frozen-manifest.json').read_text())
    ledger=json.loads((source/'spend-ledger.json').read_text())
    grouped={};rows=[]
    for phase,plan in manifest['plans'].items():
        for cell in plan['trials']:
            trial=source/phase/cell['trial_id'];result=trial/'result.json'
            if not result.exists():continue
            raw=json.loads(result.read_text());report=json.loads(clean(result.read_text()))
            profile=cell['profile'];short,title=TASK[cell['scenario_id']];defense=cell['defense'];slug=profile+'-'+short
            folder=dest/phase/slug;folder.mkdir(parents=True,exist_ok=True)
            grouped.setdefault((phase,slug),{})[cell['trial_id']]=report
            bundle=folder/'artifacts.jsonl'
            with bundle.open('a') as stream:
                for path in sorted(trial.rglob('*')):
                    if path.is_symlink():raise ValueError('Unexpected symlink source artifact')
                    if not path.is_file():continue
                    item=record(path);stream.write(json.dumps(item,ensure_ascii=False)+'\n')
                    info={k:v for k,v in item.items() if k!='content'}
                    info.update(published_file=str(bundle.relative_to(ROOT)),record_key=item['source_path']);inventory.append(info)
            patch=[]
            for event in raw.get('events',[]):
                name=event['path'];before=trial/'attempt-0/before-workspace'/name;after=trial/'attempt-0/after-workspace'/name
                try:
                    left=clean(before.read_text()).splitlines(keepends=True) if before.is_file() else []
                    right=clean(after.read_text()).splitlines(keepends=True) if after.is_file() else []
                except UnicodeDecodeError:
                    patch.append('Binary change: '+name+' (bytes retained in artifacts.jsonl)\n');continue
                patch.extend(difflib.unified_diff(left,right,fromfile='a/'+name,tofile='b/'+name))
            (folder/(defense+'.patch')).write_text(''.join(patch))
            events=raw.get('agent',{}).get('events',[]);policies=raw.get('policy_events',[])
            tools=Counter(e.get('action',{}).get('tool') for e in events if e.get('action'))
            incoming=sum(e.get('usage',{}).get('prompt_tokens',0) for e in events)
            outgoing=sum(e.get('usage',{}).get('completion_tokens',0) for e in events)
            standard=sum(e.get('usage',{}).get('prompt_tokens',0)*(750 if profile=='gpt' else (100 if e['usage']['prompt_tokens']<=100000 else 500))
                         +e.get('usage',{}).get('completion_tokens',0)*(4500 if profile=='gpt' else (500 if e['usage']['prompt_tokens']<=100000 else 2500)) for e in events if e.get('usage'))
            requests=[r for r in ledger['requests'] if r['trial_id']==cell['trial_id']]
            settled=[r for r in requests if r['status']=='settled'];uncertain=[r for r in requests if r['status']!='settled']
            if sum(r.get('prompt_tokens',0) for r in settled)!=incoming or sum(r.get('completion_tokens',0) for r in settled)!=outgoing:
                raise ValueError('Ledger and returned usage differ')
            parse=sum('parse_error' in e.get('observation',{}) for e in events)
            act=raw.get('action_scope_summary',{})
            row=dict(phase=phase,trial_id=cell['trial_id'],profile=profile,task=short,scenario_id=cell['scenario_id'],defense=defense,
                **{k:raw.get(k) for k in ('status','trial_valid','observation_valid','task_success','out_of_scope_observed','scope_compliant_success')},
                model_calls=len(events),successful_api_responses=len(settled),uncertain_requests=len(uncertain),prompt_tokens=incoming,completion_tokens=outgoing,
                standard_cost_estimate_nano_usd=standard,conservative_budget_debit_nano_usd=sum(r['debit_nano_usd'] for r in requests),
                parse_errors=parse,tools=dict(tools),questions=sum(e.get('asked') is True for e in policies),
                approved=sum(e.get('approved') is True for e in policies),denied=sum(e.get('approved') is False for e in policies),
                blocked=sum(e.get('blocked') is True for e in policies),outside_scope_requests=act.get('outside_scope_requests'),
                unknown_requests=act.get('unknown_requests'),elapsed_seconds=raw.get('agent',{}).get('elapsed_seconds'),
                models_returned=sorted({e['model_returned'] for e in events if e.get('model_returned')}),
                changed_paths=[e['path'] for e in raw.get('events',[])],
                report_bundle=str((folder/'reports.json').relative_to(dest)),report_record_key=cell['trial_id'],
                patch=str((folder/(defense+'.patch')).relative_to(dest)))
            rows.append(row)
            if phase!='core':continue
            status='통과' if row['task_success'] is True else ('실패' if row['task_success'] is False else '미관측')
            fs='없음' if row['out_of_scope_observed'] is False else ('있음' if row['out_of_scope_observed'] is True else '미관측')
            link='../../evidence/defense-comparison/live/core/'+slug
            note=f'''# {profile.upper()} {short} {defense} — {title}\n\n[실행 전 조건·선택 이유](../20261030-defense-comparison-protocol.md)와 같은 기준으로 실행한 방어 비교 1셀이다. 사용자 위임 AI 결정이며 공동 설계 채택/독립 사람 라벨과 구분한다.\n\n- trial_id: `{cell['trial_id']}`\n- 상태: `{row['status']}`; trial_valid={row['trial_valid']}, observation_valid={row['observation_valid']}.\n- 최종 기능: **{status}**; 요청 밖 최종 파일 변경: **{fs}**.\n- 방어: `{defense}`; 한국어, environment-v2, 기존 fixture/독립 최종 evaluator. 24단계/300초/응답 4096토큰, 자동 HTTP 재시도 0.\n- 반환 모델: {', '.join('`'+x+'`' for x in row['models_returned'])}.\n- 변경 파일: {', '.join('`'+x+'`' for x in row['changed_paths']) or '없음'}.\n- 행동: {', '.join(str(k)+' '+str(v)+'회' for k,v in tools.items())}.\n- 모의 질문 {row['questions']}회, 승인 {row['approved']}회, 거절 {row['denied']}회, 차단 {row['blocked']}회. 실제 사람이 매번 답한 기록이 아니다.\n- 요청 밖 행동 {row['outside_scope_requests']}회, UNKNOWN {row['unknown_requests']}회.\n- 정상 API 응답 {row['successful_api_responses']}개, 불확실 요청 {row['uncertain_requests']}개; 입력 {incoming:,}/출력 {outgoing:,}토큰. 형식 오류 {parse}건.\n- 표준 토큰 비용 추정 ${standard/1e9:.8f}; 보수 장부 차감 ${row['conservative_budget_debit_nano_usd']/1e9:.8f}. 실제 청구액은 미확인이다.\n\n[전체 보고서 묶음]({link}/reports.json)의 records[`{cell['trial_id']}`]에서 이 결과를 찾을 수 있다. [모델 코드 변경]({link}/{defense}.patch) · [모든 원시 자산·이벤트·이전/이후 파일]({link}/artifacts.jsonl) · [원본/공유 hash 목록](../../evidence/defense-comparison/live/export-manifest.json).\n\nD0와의 차이 및 표본/측정 한계는 [전체 결과](../20261030-defense-comparison-results.md)를 함께 본다. 이 한 셀로 일반 성능이나 안전 효과를 결론내리지 않는다.\n'''
            (notes/(slug+'-'+defense+'.md')).write_text(note)
    for (phase,slug),reports in grouped.items():save_json(dest/phase/slug/'reports.json',{'evidence_type':'llm','records':reports})
    totals={}
    for phase in ('preflight','core'):
        totals[phase]={}
        for profile in ('gpt','claude'):
            selected=[r for r in rows if r['phase']==phase and r['profile']==profile]
            total={k:sum(r[k] for r in selected) for k in ('successful_api_responses','uncertain_requests','prompt_tokens','completion_tokens','standard_cost_estimate_nano_usd','conservative_budget_debit_nano_usd','parse_errors','questions','approved','denied','blocked')}
            total.update(completed=len(selected),successes=sum(r['task_success'] is True for r in selected),
                         fs_violations=sum(r['out_of_scope_observed'] is True for r in selected),valid=sum(r['trial_valid'] is True and r['observation_valid'] is True for r in selected))
            totals[phase][profile]=total
    cumulative={profile:ledger['carried_forward_debit_nano_usd'][profile]+sum(r['debit_nano_usd'] for r in ledger['requests'] if r['profile']==profile) for profile in ('gpt','claude')}
    save_json(dest/'summary.json',dict(schema_version='defense-comparison-results-v0.1',evidence_type='llm',receipt=receipt,
        planned={'preflight':6,'core':24},phase_totals=totals,trials=rows,
        carried_forward_debit_nano_usd=ledger['carried_forward_debit_nano_usd'],cumulative_debit_nano_usd=cumulative,
        new_requests=len(ledger['requests']),all_new_requests_settled=all(r['status']=='settled' for r in ledger['requests']),
        billing_verified=False,team_adopted=False,independent_human_labels=False,main_study=False))
    save_json(dest/'export-manifest.json',dict(schema_version='redacted-artifact-export-v0.1',source_session=source.name,
        transformations=['Exact API key strings redacted if present','Personal absolute paths replaced','Binary contents preserved as base64; no truncation'],
        source_files=len(inventory),records=inventory,note='Group reports are readable derived views; original result.json text is also preserved in the artifact bundles. Shared redacted plans are not executable approvals.'))
    for path in list(dest.rglob('*'))+list(notes.rglob('*')):
        if path.is_file() and any(secret and secret.encode() in path.read_bytes() for secret in secrets):raise ValueError('Credential in published evidence')
    print(json.dumps({'completed':len(rows),'phase_totals':totals,'cumulative_debit_nano_usd':cumulative,'source_files':len(inventory)},ensure_ascii=False))


if __name__=='__main__':main()
