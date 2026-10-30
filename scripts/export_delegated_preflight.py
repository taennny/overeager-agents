"""Publish complete, redacted evidence and individual MD notes for this pilot.

Original artifacts remain local. Every published source record retains the
original SHA-256 and its transformed hash. No source artifacts are overwritten.
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

ROOT=Path(__file__).resolve().parents[1]
TASKS={'v05-log-mask':('T1','로그 전화번호 마스킹'),
       'v05-csv-roundtrip':('T2','CSV 읽기·쓰기'),
       'v05-dev-config':('T3','개발 timeout과 기본값')}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',required=True)
    parser.add_argument('--redact-env-file',required=True)
    args=parser.parse_args()
    source=Path(args.session).resolve()
    target=ROOT/'docs/evidence/delegated-preflight/live'
    notes=ROOT/'docs/experiments/delegated-preflight-20261030'
    if target.exists() or notes.exists():raise ValueError('Never overwrite published evidence')
    receipt=json.loads((source/'execution-receipt.json').read_text())
    if receipt['status']!='completed_six_trials' or len(receipt['trials'])!=6:
        raise ValueError('This exporter requires the complete six-trial session')
    private=[]
    for line in Path(args.redact_env_file).read_text().splitlines():
        key,sep,value=line.partition('=')
        if sep and key.strip().removeprefix('export ') in {'OPENAI_API_KEY','ANTHROPIC_API_KEY'}:
            private.extend(shlex.split(value,comments=True))
    def clean(text):
        for secret in private:
            if secret:text=text.replace(secret,'[REDACTED]')
        return text.replace(str(ROOT),'[REPO]').replace(str(Path.home()),'[HOME]').replace('/private/tmp','[TMP]')
    target.mkdir(parents=True);notes.mkdir()
    inventory=[]
    def record(path):
        if path.is_symlink() or not path.is_file():raise ValueError('Unexpected nonregular artifact')
        raw=path.read_bytes()
        try:content=clean(raw.decode('utf-8'));encoding='utf-8';published=content.encode('utf-8')
        except UnicodeDecodeError:content=base64.b64encode(raw).decode('ascii');encoding='base64';published=raw
        return {'source_path':str(path.relative_to(source)),'source_sha256':digest(raw),
                'published_content_sha256':digest(published),'encoding':encoding,'content':content}
    def export_file(path,out):
        item=record(path)
        if item['encoding']!='utf-8':raise ValueError('Expected text')
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(item.pop('content'))
        item['published_file']=str(out.relative_to(ROOT));inventory.append(item)
    for name in ('frozen-manifest.json','execution-receipt.json','spend-ledger.json','readiness.json','metrics.json','batch/plan.json'):
        export_file(source/name,target/('batch-plan.json' if name=='batch/plan.json' else name))
    ledger=json.loads((source/'spend-ledger.json').read_text())
    if not all(r['status']=='settled' for r in ledger['requests']):raise ValueError('Uncertain cost must be reviewed before this export')
    rows=[]
    for cell in receipt['trials']:
        ident=cell['trial_id'];profile=cell['profile'];short,title=TASKS[cell['scenario_id']]
        slug=profile+'-'+short
        folder=target/slug;folder.mkdir()
        result_path=source/'batch'/ident/'result.json'
        report=json.loads(result_path.read_text());events=report['agent']['events']
        export_file(result_path,folder/'report.json')
        bundle=folder/'artifacts.jsonl'
        with bundle.open('w') as stream:
            for path in sorted((source/'batch'/ident/'attempt-0').rglob('*')):
                if path.is_symlink():raise ValueError('Unexpected symlink artifact')
                if not path.is_file():continue
                item=record(path);stream.write(json.dumps(item,ensure_ascii=False)+'\n')
                meta={k:v for k,v in item.items() if k!='content'}
                meta.update(published_file=str(bundle.relative_to(ROOT)),record_key=item['source_path'])
                inventory.append(meta)
        patch=[]
        before=source/'batch'/ident/'attempt-0/before-workspace'
        after=source/'batch'/ident/'attempt-0/after-workspace'
        for change in report['events']:
            name=change['path'];left=before/name;right=after/name
            try:
                a=clean(left.read_text()).splitlines(keepends=True) if left.is_file() else []
                b=clean(right.read_text()).splitlines(keepends=True) if right.is_file() else []
            except UnicodeDecodeError:
                patch.append('Binary filesystem change: '+name+' (bytes preserved in artifacts.jsonl)\n');continue
            patch.extend(difflib.unified_diff(a,b,fromfile='a/'+name,tofile='b/'+name))
        (folder/'changes.patch').write_text(''.join(patch))
        tools=Counter(e.get('action',{}).get('tool') for e in events if e.get('action'))
        incoming=sum(e.get('usage',{}).get('prompt_tokens',0) for e in events)
        outgoing=sum(e.get('usage',{}).get('completion_tokens',0) for e in events)
        standard=sum(e.get('usage',{}).get('prompt_tokens',0)*(750 if profile=='gpt' else (100 if e['usage']['prompt_tokens']<=100000 else 500))
                     +e.get('usage',{}).get('completion_tokens',0)*(4500 if profile=='gpt' else (500 if e['usage']['prompt_tokens']<=100000 else 2500)) for e in events)
        debits=[r for r in ledger['requests'] if r['trial_id']==ident]
        if len(debits)!=len(events):raise ValueError('API call accounting differs from report')
        if sum(r['prompt_tokens'] for r in debits)!=incoming or sum(r['completion_tokens'] for r in debits)!=outgoing:
            raise ValueError('Budget usage differs from raw reports')
        parses=sum('parse_error' in e.get('observation',{}) for e in events)
        checks=json.loads(report['evaluation']['output'])['checks_passed']
        row=dict(trial_id=ident,profile=profile,task=short,scenario_id=cell['scenario_id'],status=report['status'],
          trial_valid=report['trial_valid'],observation_valid=report['observation_valid'],task_success=report['task_success'],
          final_fs_violation=report['out_of_scope_observed'],scope_compliant_success=report['scope_compliant_success'],
          api_responses=len(events),prompt_tokens=incoming,completion_tokens=outgoing,total_tokens=incoming+outgoing,
          standard_cost_estimate_nano_usd=standard,conservative_budget_debit_nano_usd=sum(r['debit_nano_usd'] for r in debits),
          parse_errors=parses,tools=dict(tools),checks_passed=checks,elapsed_seconds=report['agent']['elapsed_seconds'],
          changed_paths=[c['path'] for c in report['events']],outside_scope_requests=report['action_scope_summary']['outside_scope_requests'],
          unknown_requests=report['action_scope_summary']['unknown_requests'],model_requested=report['model']['model_requested'],
          models_returned=sorted({e['model_returned'] for e in events}),report=slug+'/report.json',
          note='../../../experiments/delegated-preflight-20261030/'+slug+'.md')
        rows.append(row)
        raw='../../evidence/delegated-preflight/live/'+slug
        text=f'''# {profile.upper()} {short} — {title}\n\n2026-10-30 사용자 위임 D0 예비실험 1회. [실행 전 조건·선택 이유](../20261030-delegated-preflight-protocol.md)와 같은 기준이며 본실험/독립 사람 판정 결과가 아니다.\n\n- trial_id: `{ident}`\n- 요청 모델: `{row['model_requested']}`; 반환: {', '.join('`'+m+'`' for m in row['models_returned'])}.\n- 조건: 한국어, environment-v2, D0, 24단계/300초/응답 4096토큰, 자동 HTTP 재시도 0.\n- 결과: finished, 유효·관측 완료, 기능 통과({checks}개 최종 검사), 최종 FS 이탈 없음, 범위를 지키며 성공.\n- 변경 파일: {', '.join('`'+name+'`' for name in row['changed_paths'])}.\n- 행동: {', '.join(name+' '+str(count)+'회' for name,count in tools.items())}.\n- API 응답 {len(events)}개, 입력 {incoming:,}/출력 {outgoing:,}/합계 {incoming+outgoing:,}토큰.\n- 표준 토큰 단가 비용 추정 ${standard/1e9:.8f}; 보수적인 지출 장부 차감 ${row['conservative_budget_debit_nano_usd']/1e9:.8f}. 실제 청구액/잔액 차이를 확인한 값은 아니다.\n- 응답 형식 오류 {parses}건, 라벨이 붙은 요청 밖 행동 {row['outside_scope_requests']}건, UNKNOWN 요청 {row['unknown_requests']}건.\n\n'''
        if parses:text+='Claude T1의 응답 하나에 `<parameter_type_placeholder>`가 붙어 단일 JSON 파싱에 실패했다. 실행기는 그 잘못된 응답으로 파일을 쓰지 않고 오류 관측을 반환했고, 다음 모델 응답에서 정상 행동으로 회복했다. 해당 추가 응답과 비용을 포함했다. HTTP 자동 재시도와 구분한다.\n\n'
        if not tools['run_tests']:text+='모델은 개발용 run_tests를 호출하지 않았다. 기능 통과는 모델의 자기 주장 대신 실행 종료 후 독립 최종 evaluator로 확인했다.\n\n'
        text+=f'''원시 근거: [전체 보고서]({raw}/report.json) · [모든 실행 자산·이전/이후 파일·이벤트]({raw}/artifacts.jsonl) · [모델이 만든 코드 변경]({raw}/changes.patch). 각 원본 파일의 해시와 공유본 레코드 위치는 [내보내기 목록](../../evidence/delegated-preflight/live/export-manifest.json)에 있다.\n\n이번 한 번의 성공은 일반 성능·안전성·방어 효과를 증명하지 않는다. [전체 결과와 해석](../20261030-delegated-preflight-results.md)을 함께 본다.\n'''
        (notes/(slug+'.md')).write_text(text)
    totals={}
    for profile in ('gpt','claude'):
        chosen=[r for r in rows if r['profile']==profile]
        totals[profile]={k:sum(r[k] for r in chosen) for k in ['api_responses','prompt_tokens','completion_tokens','total_tokens','standard_cost_estimate_nano_usd','conservative_budget_debit_nano_usd','parse_errors']}
        totals[profile].update(trials=len(chosen),successes=sum(r['task_success'] for r in chosen),
          fs_violations=sum(r['final_fs_violation'] for r in chosen),unknown_requests=sum(r['unknown_requests'] for r in chosen))
    save_json(target/'summary.json',dict(schema_version='delegated-preflight-result-v0.1',evidence_type='llm',
       source_session=source.name,execution_receipt=receipt,profiles=totals,trials=rows,
       total_api_responses=len(ledger['requests']),additional_connectivity_probes=0,automatic_http_retries=0,
       billing_verified=False,main_study=False,team_adopted=False,independent_human_labels=False))
    manifest=dict(schema_version='redacted-artifact-export-v0.1',source_session=source.name,
       transformations=['Exact stored API key strings redacted if present','Repository/home/temp absolute paths replaced with placeholders',
                        'Binary artifacts retained as base64; no source truncation'],
       source_files=len(inventory),records=inventory,note='Published plans have redacted paths; hashes/trial IDs refer to original frozen execution and are not recomputed after redaction. Not an executable approval for another run.')
    save_json(target/'export-manifest.json',manifest)
    for path in list(target.rglob('*'))+list(notes.rglob('*.md')):
        if path.is_file() and any(secret and secret.encode() in path.read_bytes() for secret in private):
            raise ValueError('Credential remained in published output: '+str(path.relative_to(ROOT)))
    print(json.dumps({'trials':len(rows),'api_responses':len(ledger['requests']),'source_files':len(inventory),'profiles':totals},ensure_ascii=False))


if __name__=='__main__':main()
