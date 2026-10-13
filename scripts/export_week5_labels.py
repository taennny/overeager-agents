"""Two independent annotation sheets. Raw traces stay local; labels start blank."""
import argparse
import csv
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scope_lab.cli import read_json
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('batch');p.add_argument('--out',required=True);a=p.parse_args()
root=Path(a.batch).resolve();out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
plan=read_json(root/'plan.json')['plan']; rows=[]
for c in plan['trials']:
    result=root/c['trial_id']/'result.json'
    if not result.exists():continue
    r=read_json(result)
    if r.get('cell')!=c:raise ValueError('Cell mismatch')
    attempt=root/c['trial_id']/('attempt-'+str(r['selected_attempt']))
    rows.append(dict(trial_id=c['trial_id'],scope=str(attempt/'scope.json'),
                     task=str(attempt/'prompt.txt'),events=str(attempt/'events.jsonl'),
                     before=str(attempt/'before-workspace'),after=str(attempt/'after-workspace'),
                     fs_violation='',over_refusal='',legitimate_alternative='',stop_reason='',
                     semantic_scope_violation='',evidence='',reviewer='',reviewed_at=''))
for reviewer in ('A','B'):
    with (out/('reviewer_'+reviewer+'.csv')).open('x',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['trial_id'])
        writer.writeheader();writer.writerows(rows)
print('Prepared independent sheets; no human labels inferred. Trace content may reveal conditions, so this is not full experimental blinding.')
