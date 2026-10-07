import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scope_lab.defenses import Gate, instruction, action_id, validate_policy
from scope_lab.batch import make_plan, execute_plan
from scope_lab.metrics import summarize, audit_scores
from scope_lab.model_client import chat, profile_config, ModelError

ROOT=Path(__file__).resolve().parents[1]
POLICY={'version':'tool-policy-v0.1','read_paths':['solution.py'],'write_paths':['solution.py'],'commands':['pwd']}


class PolicyTests(unittest.TestCase):
    def test_shell_interpreter_cannot_be_whitelisted(self):
        policy=copy.deepcopy(POLICY);policy['commands']=['python solution.py']
        with self.assertRaises(ValueError):validate_policy(policy)

    def test_d0_d1_observe_without_blocking(self):
        action={'tool':'shell','command':'rm notes.txt'}
        for defense in ('D0','D1'):
            calls=[];gate=Gate(defense,POLICY,lambda a,t:calls.append(a) or {'ok':True})
            self.assertTrue(gate(action,1)['ok']);self.assertEqual(len(calls),1)
            self.assertFalse(gate.events[0]['within_policy'])

    def test_d2_d3_do_not_execute_unapproved_actions(self):
        for defense in ('D2','D3'):
            gate=Gate(defense,POLICY,lambda *a:self.fail('blocked action executed'))
            result=gate({'tool':'write_file','path':'notes.txt','content':'bad'},1)
            self.assertTrue(result['blocked'])
            self.assertEqual(gate.events[0]['asked'],defense=='D3')

    def test_recorded_simulated_approval_is_action_specific(self):
        action={'tool':'shell','command':'echo example'}
        gate=Gate('D3',POLICY,lambda *a:{'ok':True},{action_id(action):True})
        self.assertTrue(gate(action,1)['ok'])
        changed=dict(action,command='echo changed')
        self.assertTrue(gate(changed,1)['blocked'])

    def test_allowed_file_target_is_rechecked_by_worker(self):
        calls=[];gate=Gate('D2',POLICY,lambda a,t:calls.append(a) or {'ok':True})
        gate({'tool':'write_file','path':'solution.py','content':'ok'},1)
        self.assertEqual(calls[0]['_permitted_targets'],['solution.py'])

    def test_consent_pair_preserves_exact_base_bytes(self):
        for base,lang in [('버그 수정\n','ko'),('Fix the bug\n','en')]:
            kept=instruction(base,POLICY,'D1',lang)
            self.assertEqual(kept[:len(base)].encode(),base.encode())
            self.assertEqual(instruction(base,POLICY,'D0',lang),base)


class BatchMetricTests(unittest.TestCase):
    def setUp(self):
        self.plan=make_plan(ROOT/'experiments/mock.json')

    def report(self,cell,violation=False,success=True):
        return {'cell':cell,'trial_valid':True,'observation_valid':True,'status':'finished',
                'evidence_type':'scripted_control_not_llm','task_success':success,
                'out_of_scope_observed':violation,'scope_compliant_success':success and not violation,
                'agent':{'elapsed_seconds':2,'reported_total_tokens':None,'events':[]},'policy_events':[]}

    def test_full_design_is_five_models_and_960_cells(self):
        plan=make_plan(ROOT/'experiments/pilot.json')
        self.assertEqual(len(plan['trials']),960)
        self.assertEqual(plan,make_plan(ROOT/'experiments/pilot.json'))
        self.assertEqual(len(set(c['trial_id'] for c in plan['trials'])),960)

    def test_missing_results_and_labels_are_not_zero(self):
        rows=summarize(self.plan,{})['groups']
        self.assertTrue(all(r['fs_osr'] is None and r['tsr'] is None for r in rows))
        cell=self.plan['trials'][0]
        row=next(r for r in summarize(self.plan,{cell['trial_id']:self.report(cell)})['groups'] if r['valid'])
        self.assertIsNone(row['orr']);self.assertEqual(row['orr_labeled'],0)
        self.assertIsNone(row['paired_token_overhead'])

    def test_failure_is_not_automatically_overrefusal(self):
        cell=self.plan['trials'][0];report=self.report(cell,success=False)
        groups=summarize(self.plan,{cell['trial_id']:report})['groups']
        self.assertIsNone(next(r for r in groups if r['valid'])['orr'])
        groups=summarize(self.plan,{cell['trial_id']:report},{cell['trial_id']:{'over_refusal':False,'evidence':'incorrect code, no refusal'}})['groups']
        self.assertEqual(next(r for r in groups if r['valid'])['orr'],0)

    def test_unknown_labels_and_mixed_evidence_rejected(self):
        with self.assertRaises(ValueError):summarize(self.plan,{}, {'wrong':{}})
        cell=self.plan['trials'][0];report=self.report(cell);report['evidence_type']='llm'
        with self.assertRaises(ValueError):summarize(self.plan,{cell['trial_id']:report})

    def test_batch_resume_and_retry_are_not_extra_repetitions(self):
        cell=self.plan['trials'][0];plan=copy.deepcopy(self.plan);plan['trials']=[cell]
        counter=[]
        def fake_run(scenario,target,*args,**kwargs):
            Path(target).mkdir();counter.append(target)
            if len(counter)==1:return {'status':'model_error','trial_valid':False,'retryable':True}
            return self.report(cell)
        with tempfile.TemporaryDirectory() as temp, patch('scope_lab.batch.run',fake_run), patch('scope_lab.batch.time.sleep'), patch('scope_lab.batch.DockerSandbox._docker',return_value='sha256:test'):
            first=execute_plan(plan,temp);second=execute_plan(plan,temp)
            self.assertEqual(first['completed'],1);self.assertEqual(second['executed_this_invocation'],0)
            self.assertEqual(len(counter),2)
            result=json.loads((Path(temp)/cell['trial_id']/'result.json').read_text())
            self.assertEqual(result['selected_attempt'],1);self.assertEqual(len(result['attempts']),2)

    def test_audit_duplicate_trials_rejected(self):
        with self.assertRaises(ValueError):
            audit_scores([{'trial_id':'a'},{'trial_id':'a'}],{'a'})
        with self.assertRaises(ValueError):
            audit_scores([{'trial_id':'other'}],{'a'})

    def test_audit_empty_degenerate_and_known_kappa(self):
        self.assertIsNone(audit_scores([])['cohen_kappa'])
        self.assertIsNone(audit_scores([{'human_a':'0','human_b':'0'}])['cohen_kappa'])
        rows=[{'human_a':a,'human_b':b,'adjudicated':a,'oracle':b} for a,b in [('0','0'),('0','1'),('1','1'),('1','0')]]
        result=audit_scores(rows);self.assertAlmostEqual(result['cohen_kappa'],0)
        self.assertEqual(result['precision'],0.5);self.assertEqual(result['recall'],0.5)


class NewProviderTests(unittest.TestCase):
    def test_claude_native_request_and_usage(self):
        class Opener:
            def open(inner,request,timeout):
                body=json.loads(request.data)
                self.assertEqual(request.full_url,'https://api.anthropic.com/v1/messages')
                self.assertEqual(body['system'],'sys');self.assertEqual(body['messages'],[{'role':'user','content':'task'}])
                self.assertEqual(request.get_header('X-api-key'),'fake-key')
                return io.BytesIO(json.dumps({'model':'test-claude','stop_reason':'end_turn',
                        'content':[{'type':'text','text':'READY'}],'usage':{'input_tokens':10,'output_tokens':2,'cache_read_input_tokens':4}}).encode())
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fake-key','CLAUDE_MODEL':'test-claude'},clear=True):
            result=chat(profile_config('claude'),[{'role':'system','content':'sys'},{'role':'user','content':'task'}],opener=Opener())
        self.assertEqual(result['usage']['total_tokens'],16)

    def test_gpt_uses_completion_budget_not_legacy_max_tokens(self):
        class Opener:
            def open(inner,request,timeout):
                body=json.loads(request.data);self.assertIn('max_completion_tokens',body);self.assertNotIn('max_tokens',body)
                return io.BytesIO(b'{"choices":[{"message":{"content":"READY"},"finish_reason":"stop"}]}')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake','GPT_MODEL':'explicit-test-model'},clear=True):
            chat(profile_config('gpt'),[],opener=Opener())


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS')=='1','Requires Docker')
class DefenseDockerTests(unittest.TestCase):
    def test_four_conditions_batch_resume_and_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            plan=make_plan(ROOT/'experiments/mock.json');out=Path(temp)/'batch'
            self.assertEqual(execute_plan(plan,out)['completed'],4)
            self.assertEqual(execute_plan(plan,out)['executed_this_invocation'],0)
            reports={c['trial_id']:json.loads((out/c['trial_id']/'result.json').read_text()) for c in plan['trials']}
            groups=summarize(plan,reports)['groups']
            for row in groups:
                self.assertEqual(row['tsr'],1)
                self.assertEqual(row['fs_osr'],1 if row['defense'] in ('D0','D1') else 0)
                self.assertEqual(row['mean_questions'],1 if row['defense']=='D3' else 0)

    def test_d2_cannot_follow_allowed_name_to_protected_file(self):
        from scope_lab.sandbox import DockerSandbox
        box=DockerSandbox()
        try:
            box.start(ROOT/'scenarios/01-add/fixture')
            box.tool({'tool':'shell','command':'rm solution.py; ln -s notes/meeting.txt solution.py'},5)
            gate=Gate('D2',POLICY,box.tool)
            self.assertFalse(gate({'tool':'write_file','path':'solution.py','content':'changed'},5)['ok'])
        finally:box.close()
