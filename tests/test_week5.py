import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scope_lab.agent import build_system_prompt, run_loop
from scope_lab.batch import make_plan
from scope_lab.defenses import instruction, defense_label, CONSENT_BLOCKS
from scope_lab.model_client import chat, make_completion, inference_metadata, ModelError
from scope_lab.readiness import review

ROOT=Path(__file__).resolve().parents[1]
class Week5Tests(unittest.TestCase):
    def test_new_matrix_does_not_duplicate_d0_or_d1(self):
        plan=make_plan(ROOT/'experiments/v04-pilot.json')
        self.assertEqual(len(plan['trials']),48)
        self.assertEqual(sum(c['defense']=='D0' for c in plan['trials']),6)
        self.assertEqual(sum(c['defense']=='D1' for c in plan['trials']),6)
        self.assertEqual(len(make_plan(ROOT/'experiments/v04-preflight.json')['trials']),6)
        self.assertEqual(len(make_plan(ROOT/'experiments/v04-controls.json')['trials']),72)
        self.assertEqual(len(make_plan(ROOT/'experiments/v03-pilot.json')['trials']),42)
    def test_consent_is_only_d0_d1_prompt_difference_with_fixed_tool(self):
        base=build_system_prompt(True,'environment-v1')
        self.assertIn('run_tests',base)
        self.assertEqual(instruction(base,None,'D1','ko'),base+'\n\n'+CONSENT_BLOCKS['ko'])
        seen=[]
        run_loop('task',lambda msgs,t:seen.append(msgs[:]) or {'content':'{"tool":"finish","message":"done"}'},
                 lambda *a:None,system_prompt=instruction(base,None,'D1','ko'))
        self.assertEqual(seen[0][0]['content'],base+'\n\n'+CONSENT_BLOCKS['ko'])
    def test_scoped_approval_is_not_deny_default(self):
        self.assertEqual(defense_label('D3',approval_mode='scope_simulated'),'D3-scope-simulated')
        self.assertEqual(defense_label('D3'),'D3-deny-default')
    def test_new_budget_reaches_wire_and_metadata(self):
        config=dict(protocol='ollama',base_url='http://127.0.0.1:11435',model='example:1',
                    key_env=None,output_format='json',num_ctx=8192,max_tokens=4096)
        class Opener:
            def open(inner,request,timeout):
                body=json.loads(request.data)
                self.assertEqual(body['options']['num_ctx'],8192)
                self.assertEqual(body['options']['num_predict'],4096)
                return io.BytesIO(b'{"done":true,"done_reason":"stop","message":{"content":"{}"}}')
        with patch('scope_lab.model_client.urllib.request.build_opener',return_value=Opener()):
            make_completion(config)([],10)
        self.assertEqual(inference_metadata(config,'qwen')['max_tokens'],4096)
    def test_incomplete_response_cannot_dispatch_partial_action(self):
        class Opener:
            def open(self,request,timeout):
                return io.BytesIO(b'{"done":false,"done_reason":"length","eval_count":4096,"message":{"content":"sensitive partial text"}}')
        config=dict(protocol='ollama',base_url='http://127.0.0.1:11435',model='example',key_env=None)
        def complete(*args):return chat(config,[],opener=Opener())
        result=run_loop('task',complete,lambda *a:self.fail('incomplete response executed'))
        self.assertEqual(result['status'],'model_error')
        self.assertEqual(result['events'][0]['model_diagnostics']['eval_count'],4096)
        self.assertNotIn('sensitive',json.dumps(result))
    def test_readiness_requires_each_task_d0_success_and_no_missing(self):
        plan=make_plan(ROOT/'experiments/v04-preflight.json')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'plan.json').write_text(json.dumps({'plan':plan}))
            self.assertEqual(review(root)['compatibility_gate'],'hold')
            for c in plan['trials']:
                p=root/c['trial_id'];p.mkdir()
                report=dict(cell=c,status='finished',trial_valid=True,observation_valid=True,
                            task_success=True,out_of_scope_observed=False,evidence_type='llm')
                (p/'result.json').write_text(json.dumps(report))
            self.assertEqual(review(root)['compatibility_gate'],'ready_for_team_review')
            first=root/plan['trials'][0]['trial_id']/'result.json'
            r=json.loads(first.read_text());r['task_success']=False;first.write_text(json.dumps(r))
            self.assertEqual(review(root)['compatibility_gate'],'hold')
            r['cell']['repeat']=7;first.write_text(json.dumps(r))
            with self.assertRaises(ValueError):review(root)
