"""Export blind-label worksheets; don't fabricate human annotations."""
import argparse
import csv
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scope_lab.cli import read_json
p=argparse.ArgumentParser();p.add_argument('batch');p.add_argument('--out',required=True);args=p.parse_args()
folder=Path(args.batch);out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
plan=read_json(folder/'plan.json')['plan'];items=[];answers=[]
for cell in plan['trials']:
    path=folder/cell['trial_id']/'result.json'
    if not path.exists():continue
    report=read_json(path)
    if not report.get('observation_valid'):continue
    attempt=folder/cell['trial_id']/('attempt-'+str(report['selected_attempt']))
    items.append({'trial_id':cell['trial_id'],'scenario':cell['scenario'],
                  'before':str(attempt/'before-workspace'),'after':str(attempt/'after-workspace'),
                  'scope':str(attempt/'scope.json'),'human_a':'','human_b':'','adjudicated':''})
    answers.append({'trial_id':cell['trial_id'],'oracle':int(report['out_of_scope_observed'])})
for name,rows in [('blind-items.csv',items),('oracle-key.csv',answers)]:
    with (out/name).open('w',newline='') as f:
        if rows:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print('Human labels left blank. Join oracle-key only after independent annotation.')
