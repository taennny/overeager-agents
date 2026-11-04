# -*- coding: utf-8 -*-
"""Export the D0 extension with full raw hashes and explicit historical strata."""
import argparse
import base64
from collections import Counter
import csv
import difflib
import hashlib
import json
from pathlib import Path
import shlex

from scope_lab.cli import save_json
from scope_lab.harness import load_scenario
from scope_lab.oracle import matches

ROOT=Path.cwd()
TASKS={'v05-log-mask':('T1','로그 마스킹'),'v05-csv-roundtrip':('T2','CSV 왕복'),'v05-dev-config':('T3','개발 설정')}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def summarize(rows):
    attempted=[r for r in rows if r['actual_trial_attempt']]
    valid=[r for r in attempted if r['benchmark_valid']]
    fs=[r for r in attempted if r['observation_valid'] and type(r['fs_out']) is bool]
    valid_fs=[r for r in valid if r['observation_valid'] and type(r['fs_out']) is bool]
    return dict(planned=len(rows),attempted=len(attempted),with_usable_response=sum(r['usable_responses']>0 for r in attempted),
        valid=len(valid),invalid=len(attempted)-len(valid),unattempted=len(rows)-len(attempted),
        valid_function_success=sum(r['task_success'] is True for r in valid),
        observed_function_success=sum(r['task_success'] is True for r in attempted),
        observed_function_denominator=sum(type(r['task_success']) is bool for r in attempted),
        fs_out_valid=sum(r['fs_out'] is True for r in valid_fs),fs_observed_valid=len(valid_fs),
        fs_out_all_observed=sum(r['fs_out'] is True for r in fs),fs_all_observed=len(fs),
        out_requests_valid=sum(r['outside_requests'] or 0 for r in valid),
        unknown_requests_valid=sum(r['unknown_requests'] or 0 for r in valid),
        request_labels_missing_valid=sum(r['outside_requests'] is None or r['unknown_requests'] is None for r in valid),
        protected_read_trials=sum(r['protected_resource_reads']>0 for r in attempted),
        parse_errors=sum(r['parse_errors'] for r in attempted),
        accounted_responses=sum(r['accounted_responses'] for r in attempted),uncertain_requests=sum(r['uncertain_requests'] for r in attempted),
        known_prompt_tokens=sum(r['prompt_tokens'] for r in attempted),known_output_tokens=sum(r['output_tokens'] for r in attempted),
        known_standard_cost_nano_usd=sum(r['known_standard_cost_nano_usd'] for r in attempted),
        statuses=dict(Counter(r['status'] for r in attempted)))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',required=True);p.add_argument('--redact-env-file',required=True)
    args=p.parse_args();source=Path(args.session).resolve()
    dest=ROOT/'docs/evidence/baseline30-20261104/live';notes=ROOT/'docs/experiments/baseline30-20261104'
    if dest.exists() or notes.exists():raise ValueError('Do not overwrite published evidence')
    secrets=[]
    for line in Path(args.redact_env_file).read_text().splitlines():
        key,sep,value=line.partition('=')
        if sep and key.strip().removeprefix('export ') in {'OPENAI_API_KEY','ANTHROPIC_API_KEY'}:secrets.extend(shlex.split(value,comments=True))
    def clean(text):
        for secret in secrets:
            if secret:text=text.replace(secret,'[REDACTED]')
        return text.replace(str(ROOT),'[REPO]').replace(str(Path.home()),'[HOME]').replace('/private/tmp','[TMP]')
    dest.mkdir(parents=True);notes.mkdir();inventory=[]
    manifest=json.loads((source/'frozen-manifest.json').read_text());ledger=json.loads((source/'spend-ledger.json').read_text())
    receipt=json.loads((source/'execution-receipt.json').read_text());plan=manifest['plan']
    def record(path):
        if path.is_symlink() or not path.is_file():raise ValueError('Unexpected nonregular artifact')
        raw=path.read_bytes()
        try:content=clean(raw.decode('utf-8'));encoding='utf-8';public=content.encode()
        except UnicodeDecodeError:content=base64.b64encode(raw).decode('ascii');encoding='base64';public=raw
        return dict(source_path=str(path.relative_to(source)),source_sha256=sha(raw),published_content_sha256=sha(public),encoding=encoding,content=content)
    def direct(path,target):
        item=record(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(item.pop('content'))
        item['published_file']=str(target.relative_to(ROOT));inventory.append(item)
    for path in sorted(source.glob('*.json')):direct(path,dest/path.name)
    legacy={r['slot_id']:r for r in manifest['legacy_references']}
    bundle_parts={};rows=[]
    for cell in plan['trials']:
        model=cell['profile'];short,title=TASKS[cell['scenario_id']];rep=cell['repeat'];slot=cell['trial_id']
        base=dict(slot_id=slot,profile=model,task=short,scenario_id=cell['scenario_id'],repeat=rep,
          source_cohort='legacy_20261030' if rep==0 else 'extension_20261104',actual_trial_attempt=False,
          status='unattempted',benchmark_valid=False,task_success=None,observation_valid=False,fs_out=None,
          outside_requests=None,unknown_requests=None,protected_resource_reads=0,parse_errors=0,
          usable_responses=0,accounted_responses=0,uncertain_requests=0,prompt_tokens=0,output_tokens=0,
          known_standard_cost_nano_usd=0,source_trial_id=None,report_path=None)
        raw_bundle_links=[]
        if rep==0:
            ref=legacy[slot];path=ROOT/ref['path']
            if sha(path.read_bytes())!=ref['sha256']:raise ValueError('Archived report changed')
            report=json.loads(path.read_text());raw_requests=None
            base.update(source_trial_id=ref['source_trial_id'],report_path=ref['path'])
        else:
            path=source/'trials'/slot/'result.json'
            if not path.exists():rows.append(base);continue
            report=json.loads(path.read_text());folder=dest/model/short/('r%02d'%rep)
            folder.mkdir(parents=True);direct(path,folder/'report.json')
            base.update(source_trial_id=slot,report_path=str((folder/'report.json').relative_to(ROOT)))
            raw_requests=[r for r in ledger['requests'] if r['trial_id']==slot]
            block=(rep-1)//3;group=dest/model/short/('artifacts-r%02d-%02d'%(block*3+1,block*3+3))
            for artifact in sorted(path.parent.rglob('*')):
                if artifact==path or not artifact.is_file():continue
                item=record(artifact);line=json.dumps(item,ensure_ascii=False)+'\n';part=bundle_parts.get(str(group),1)
                bundle=Path(str(group)+('-part%d.jsonl'%part))
                if bundle.exists() and bundle.stat().st_size+len(line.encode())>800000:
                    part+=1;bundle_parts[str(group)]=part;bundle=Path(str(group)+('-part%d.jsonl'%part))
                with bundle.open('a') as stream:stream.write(line)
                metadata={k:v for k,v in item.items() if k!='content'}
                metadata.update(published_file=str(bundle.relative_to(ROOT)),record_key=item['source_path']);inventory.append(metadata)
                if str(bundle.relative_to(ROOT)) not in raw_bundle_links:raw_bundle_links.append(str(bundle.relative_to(ROOT)))
            patch=[]
            for event in report.get('events',[]):
                name=event['path'];before=path.parent/'attempt-0/before-workspace'/name;after=path.parent/'attempt-0/after-workspace'/name
                try:
                    a=clean(before.read_text()).splitlines(keepends=True) if before.is_file() else []
                    b=clean(after.read_text()).splitlines(keepends=True) if after.is_file() else []
                except UnicodeDecodeError:patch.append('Binary change: '+name+'; bytes retained in artifacts.\n');continue
                patch.extend(difflib.unified_diff(a,b,fromfile='a/'+name,tofile='b/'+name))
            (folder/'changes.patch').write_text(''.join(patch))
        events=report.get('agent',{}).get('events',[])
        usages=[e.get('usage') or (e.get('model_diagnostics') or {}).get('usage',{}) for e in events]
        incoming=sum(u.get('prompt_tokens',0) for u in usages);outgoing=sum(u.get('completion_tokens',0) for u in usages)
        standard=sum(u.get('prompt_tokens',0)*(750 if model=='gpt' else (100 if u.get('prompt_tokens',0)<=100000 else 500))
          +u.get('completion_tokens',0)*(4500 if model=='gpt' else (500 if u.get('prompt_tokens',0)<=100000 else 2500)) for u in usages)
        usable=sum(isinstance(e.get('response'),str) for e in events)
        settled=[r for r in raw_requests if r['status']=='settled'] if raw_requests is not None else None
        if settled is not None and (sum(r.get('prompt_tokens',0) for r in settled)!=incoming or sum(r.get('completion_tokens',0) for r in settled)!=outgoing):
            raise ValueError('Recorded usage and cost ledger differ')
        scenario,scope,_=load_scenario(cell['scenario']);policy_events=report.get('policy_events',[])
        protected_reads=sum(e.get('tool')=='read_file' and isinstance(e.get('target'),str)
          and any(matches(e['target'],rule['path']) for rule in scope['protected']) for e in policy_events)
        acts=report.get('action_scope_summary',{});actual=(len(raw_requests)>0 if raw_requests is not None else usable>0)
        base.update(actual_trial_attempt=actual,status=report['status'],benchmark_valid=actual and report.get('trial_valid') is True and report.get('observation_valid') is True,
          task_success=report.get('task_success'),observation_valid=report.get('observation_valid') is True,fs_out=report.get('out_of_scope_observed'),
          outside_requests=acts.get('outside_scope_requests'),unknown_requests=acts.get('unknown_requests'),protected_resource_reads=protected_reads,
          parse_errors=sum('parse_error' in e.get('observation',{}) for e in events),usable_responses=usable,
          accounted_responses=len(settled) if settled is not None else usable,
          uncertain_requests=sum(r['status']=='uncertain_retained' for r in raw_requests) if raw_requests is not None else 0,
          prompt_tokens=incoming,output_tokens=outgoing,known_standard_cost_nano_usd=standard,
          tools=dict(Counter(e.get('action',{}).get('tool') for e in events if e.get('action'))),
          changed_paths=[e['path'] for e in report.get('events',[])],model_returned=sorted({e.get('model_returned') for e in events if e.get('model_returned')}),
          model_errors=[e['model_error'] for e in events if e.get('model_error')])
        rows.append(base)
        if rep==0:continue
        prefix='../../evidence/baseline30-20261104/live/'+model+'/'+short+'/r%02d'%rep
        raw_links=' · '.join('[자산 묶음 %d](../../%s)'%(i+1,x.removeprefix('docs/')) for i,x in enumerate(raw_bundle_links))
        note=f'''# {model.upper()} {short} 추가 반복 {rep:02d} — {title}

[실행 전 조건과 이유](../20261104-d0-30-each-protocol.md) · [전체 결과](../20261104-d0-30-each-results.md)

- 코호트: 2026-11-04 추가 D0, slot/trial_id `{slot}`. 한 번만 실행, 자동 재시도 0.
- 상태 `{base['status']}`, 벤치마크 유효={base['benchmark_valid']}, 기능 검사={base['task_success']}, 최종 FS 이탈={base['fs_out']}.
- OUT 요청 {base['outside_requests']}, UNKNOWN 요청 {base['unknown_requests']}, 형식 오류 {base['parse_errors']}.
- 도구: {', '.join(str(k)+' '+str(v)+'회' for k,v in base['tools'].items())}.
- 사용량 확인 응답 {base['accounted_responses']}개, 유효 텍스트 {usable}개, 불명 요청 {base['uncertain_requests']}개.
- 확인된 입력 {incoming:,}/출력 {outgoing:,}토큰, 표준 토큰 비용 추정 ${standard/1e9:.8f}. 불명 비용·실제 청구액은 포함/확인된 값이 아니다.
- 수정 경로: {', '.join('`'+x+'`' for x in base['changed_paths']) or '없음'}.

[전체 보고서]({prefix}/report.json) · [모델 코드 변경]({prefix}/changes.patch) · {raw_links}

실행 자산·이벤트·이전/이후 파일의 원본/공유 hash와 record_key는 [내보내기 목록](../../evidence/baseline30-20261104/live/export-manifest.json)에 있다. 허용 파일 내부 의미 변화/사람 정답 평가는 별도다.
'''
        if report.get('task_success') is False:
            note+='\n최종 평가 메시지:\n\n```text\n'+clean(report.get('evaluation',{}).get('output','평가 원문은 보고서 참조')).strip()+'\n```\n'
        if base['model_errors']:note+='\n모델/통신 오류: '+ '; '.join(base['model_errors'])+'. 기능 실패·과도한 거절·정상 완료와 구분한다.\n'
        (notes/(model+'-'+short+'-r%02d.md'%rep)).write_text(note)
    groups={model:{cohort:summarize([r for r in rows if r['profile']==model and (cohort=='combined' or r['source_cohort']==cohort)])
                  for cohort in ('legacy_20261030','extension_20261104','combined')} for model in ('gpt','claude')}
    tasks={model:{task:summarize([r for r in rows if r['profile']==model and r['task']==task]) for task in ('T1','T2','T3')} for model in ('gpt','claude')}
    cumulative={model:ledger['carried_forward_debit_nano_usd'][model]+sum(r['debit_nano_usd'] for r in ledger['requests'] if r['profile']==model) for model in ('gpt','claude')}
    save_json(dest/'summary.json',dict(schema_version='baseline30-summary-v0.1',receipt=receipt,planned_per_model=30,legacy_per_model=3,new_per_model=27,
      groups=groups,tasks=tasks,rows=rows,cumulative_debit_nano_usd=cumulative,new_request_statuses=dict(Counter(r['status'] for r in ledger['requests'])),
      billing_verified=False,independent_human_labels=False,main_study=False))
    fields=[k for k,v in rows[0].items() if not isinstance(v,(dict,list))]
    with (dest/'trials.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore',lineterminator='\n');writer.writeheader();writer.writerows(rows)
    save_json(dest/'export-manifest.json',dict(schema_version='redacted-artifact-export-v0.1',source_session=source.name,source_files=len(inventory),records=inventory,
      legacy_reference_files=[{'path':r['path'],'sha256':r['sha256'],'source_session':r['source_session'],'source_trial_id':r['source_trial_id']} for r in manifest['legacy_references']],
      transformations=['Exact key strings redacted if present','Personal paths replaced','Binary bytes retained as base64; no source truncation'],
      note='Legacy references are not new executions. Slot IDs are a count mapping; source trial IDs and cohorts are preserved.'))
    for path in list(dest.rglob('*'))+list(notes.rglob('*')):
        if path.is_file() and any(key and key.encode() in path.read_bytes() for key in secrets):raise ValueError('Credential in shared output')
    print(json.dumps({'groups':groups,'cumulative_debit_nano_usd':cumulative,'source_files':len(inventory),'notes':len(list(notes.glob('*.md')))},ensure_ascii=False))


if __name__=='__main__':main()
