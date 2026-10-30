import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

from scope_lab.batch import make_plan, prepare_models, digest, execute_plan
from scope_lab.design_v05 import verify_design_review
from scope_lab.model_client import ModelError
from scope_lab.spend_budget import SpendBudget

ROOT = Path(__file__).resolve().parents[1]
ENV = {'OPENAI_API_KEY': 'fake-budget-test', 'ANTHROPIC_API_KEY': 'fake-budget-test',
       'GPT_MODEL': 'gpt-5.4-mini-2026-03-17', 'CLAUDE_MODEL': 'claude-haiku-5-5',
       'GPT_BASE_URL': 'https://api.openai.com/v1', 'CLAUDE_BASE_URL': 'https://api.anthropic.com/v1'}
POLICY = ROOT/'experiments/20261030-delegated-preflight-budget.json'


class SpendBudgetTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan(ROOT/'experiments/v05-preflight.json')
        with patch.dict(os.environ, ENV, clear=True):
            self.configs = prepare_models(self.plan)
        self.cell = next(c for c in self.plan['trials'] if c['profile'] == 'gpt')

    def answer(self, incoming=100, outgoing=20):
        return dict(content='{}', model_returned=ENV['GPT_MODEL'],
                    usage={'prompt_tokens':incoming,'completion_tokens':outgoing})

    def budget(self, directory, policy=None):
        source = POLICY
        if policy is not None:
            source = Path(directory)/'policy.json'; source.write_text(json.dumps(policy))
        return SpendBudget(source, Path(directory)/'ledger.json', self.plan, self.configs)

    def test_reservation_exists_before_http_and_settles_conservatively(self):
        with tempfile.TemporaryDirectory() as d:
            budget = self.budget(d)
            def completion(*args):
                row=json.loads(budget.path.read_text())['requests'][0]
                self.assertEqual(row['status'],'reserved')
                self.assertGreater(row['debit_nano_usd'],100_000_000)
                return self.answer()
            guarded=budget.wrap(completion,'gpt',self.cell['trial_id'])
            guarded([],60)
            row=json.loads(budget.path.read_text())['requests'][0]
            self.assertEqual(row['status'],'settled')
            self.assertEqual(row['debit_nano_usd'],100*750+20*4500)
            self.assertNotIn('fake-budget-test', budget.path.read_text())

    def test_provider_cap_blocks_before_network(self):
        policy=json.loads(POLICY.read_text());policy['providers']['gpt']['cap_nano_usd']=200_000_000
        with tempfile.TemporaryDirectory() as d:
            guarded=self.budget(d,policy).wrap(lambda *a:self.fail('paid HTTP'),'gpt',self.cell['trial_id'])
            with self.assertRaisesRegex(ModelError,'before API request'):guarded([],60)

    def test_trial_cap_blocks_even_with_provider_money_left(self):
        with tempfile.TemporaryDirectory() as d:
            budget=self.budget(d)
            guarded=budget.wrap(lambda *a:self.answer(135168,4096),'gpt',self.cell['trial_id'])
            for _ in range(4):guarded([],60)
            with self.assertRaisesRegex(ModelError,'remaining cap'):guarded([],60)
            self.assertLess(sum(r['debit_nano_usd'] for r in json.loads(budget.path.read_text())['requests']),500_000_000)

    def test_failed_response_remains_reserved_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            budget=self.budget(d)
            def failed(*args):raise ModelError('synthetic timeout')
            with self.assertRaisesRegex(ModelError,'synthetic'):
                budget.wrap(failed,'gpt',self.cell['trial_id'])([],60)
            after=self.budget(d)
            with self.assertRaisesRegex(ModelError,'unresolved'):
                after.wrap(lambda *a:self.fail('retry'),'gpt',self.cell['trial_id'])([],60)
            self.assertEqual(len(json.loads(after.path.read_text())['requests']),1)
            # An uncertain GPT charge cannot silently consume Claude's budget.
            cell=next(c for c in self.plan['trials'] if c['profile']=='claude')
            answer=dict(content='{}',model_returned=ENV['CLAUDE_MODEL'],usage={'prompt_tokens':1,'completion_tokens':1})
            after.wrap(lambda *a:answer,'claude',cell['trial_id'])([],60)

    def test_unknown_usage_changed_model_and_negative_usage_stop(self):
        for answer in [dict(self.answer(),usage={}),dict(self.answer(),model_returned='changed'),
                       self.answer(-1,20),self.answer(10,4097),self.answer(True,20)]:
            with self.subTest(answer=answer),tempfile.TemporaryDirectory() as d:
                budget=self.budget(d)
                with self.assertRaisesRegex(ModelError,'usage or changed'):
                    budget.wrap(lambda *a:answer,'gpt',self.cell['trial_id'])([],60)
                self.assertEqual(json.loads(budget.path.read_text())['requests'][0]['status'],'uncertain_usage_or_model')

    def test_ledger_rejects_new_plan_or_policy(self):
        with tempfile.TemporaryDirectory() as d:
            self.budget(d)
            original=self.plan['plan_id'];self.plan['plan_id']='changed'
            with self.assertRaisesRegex(ValueError,'different immutable'):self.budget(d)
            self.plan['plan_id']=original
            policy=json.loads(POLICY.read_text());policy['providers']['gpt']['cap_nano_usd']=1_000_000_000
            with self.assertRaisesRegex(ValueError,'different immutable'):self.budget(d,policy)

    def test_model_drift_or_defense_expansion_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=copy.deepcopy(self.configs);cfg['gpt']['model']='unpriced-model'
            with self.assertRaises(ValueError):SpendBudget(POLICY,Path(d)/'ledger',self.plan,cfg)
            other=make_plan(ROOT/'experiments/v05-core.json')
            with self.assertRaisesRegex(ValueError,'D0'):SpendBudget(POLICY,Path(d)/'ledger',other,self.configs)

    def test_unknown_trial_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'Unknown budget'):
                self.budget(d).wrap(lambda *a:None,'gpt','unknown')


class DelegatedReviewTests(unittest.TestCase):
    def test_delegated_decision_schema_scopes_preflight_not_team_expansion(self):
        plan=make_plan(ROOT/'experiments/v05-preflight.json')
        record=json.loads((ROOT/'experiments/20261030-delegated-preflight-review.json').read_text())
        # A synthetic local-plan copy lets CI exercise the schema without
        # pretending that its different absolute-path plan has paid approval.
        record['plan_id']=plan['plan_id']
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'review.json'
            path.write_text(json.dumps(record));verify_design_review(plan,path)
            for field,value in [('team_adopted',True),('independent_human_review',True),
                                ('reviewed_by_b','pretend person'),('assets_digest','changed'),
                                ('user_authorization','')]:
                altered=dict(record);altered[field]=value;path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):verify_design_review(plan,path)
            expanded=make_plan(ROOT/'experiments/v05-core.json')
            altered=dict(record,plan_id=expanded['plan_id'],assets_digest=digest(sorted({c['fingerprint'] for c in expanded['trials']})))
            path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,'unauthorized expansion'):verify_design_review(expanded,path)

    def test_delegated_pilot_cannot_run_without_budget(self):
        plan=make_plan(ROOT/'experiments/v05-preflight.json')
        with tempfile.TemporaryDirectory() as d:
            decision=Path(d)/'synthetic-review.json'
            record=json.loads((ROOT/'experiments/20261030-delegated-preflight-review.json').read_text())
            record.update(plan_id=plan['plan_id'],user_authorization='synthetic schema test; not paid approval')
            decision.write_text(json.dumps(record))
            with patch('scope_lab.batch.prepare_models',return_value={}),patch('scope_lab.batch.DockerSandbox',side_effect=AssertionError('No Docker/API')):
                with self.assertRaisesRegex(ValueError,'explicit spend budget'):
                    execute_plan(plan,'unused',live=True,limit=1,profile_filter='gpt',design_review=decision)


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS') == '1', 'Requires Docker')
class BudgetDockerTests(unittest.TestCase):
    def test_budgeted_delegated_batch_with_mock_http_and_real_grading(self):
        import io
        plan=make_plan(ROOT/'experiments/v05-preflight.json')
        image=os.getenv('SCOPE_V03_IMAGE','overeager-sandbox:c04-v02')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV,clear=True):
            # Preserve Docker CLI discovery under a controlled test environment.
            os.environ['PATH']=os.defpath + ':/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin'
            output=Path(d)/'batch';ledger=Path(d)/'spend.json'
            decision=Path(d)/'synthetic-decision.json'
            record=json.loads((ROOT/'experiments/20261030-delegated-preflight-review.json').read_text())
            record.update(plan_id=plan['plan_id'],user_authorization='synthetic schema test; not paid approval')
            decision.write_text(json.dumps(record))
            for profile in ('gpt','claude'):
                cell=next(c for c in plan['trials'] if c['profile']==profile)
                control=json.loads((Path(cell['scenario']).parent/'control.json').read_text())
                actions=[]
                for path,content in control['solutions'].items():
                    actions.extend([{'tool':'read_file','path':path},{'tool':'write_file','path':path,'content':content}])
                actions.extend([{'tool':'run_tests'},{'tool':'finish','message':'synthetic transport check'}])
                iterator=iter(actions)
                class Opener:
                    def open(inner,request,timeout):
                        text=json.dumps(next(iterator))
                        if profile=='claude':
                            response={'model':ENV['CLAUDE_MODEL'],'content':[{'type':'text','text':text}],
                                      'stop_reason':'end_turn','usage':{'input_tokens':10,'output_tokens':20}}
                        else:
                            response={'model':ENV['GPT_MODEL'],'choices':[{'message':{'content':text},'finish_reason':'stop'}],
                                      'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}
                        return io.BytesIO(json.dumps(response).encode())
                with patch('scope_lab.model_client.urllib.request.build_opener',return_value=Opener()):
                    result=execute_plan(plan,output,live=True,limit=1,image=image,profile_filter=profile,
                        design_review=decision,budget_policy=POLICY,budget_ledger=ledger)
                report=json.loads((output/cell['trial_id']/'result.json').read_text())
                self.assertTrue(report['task_success'])
                self.assertFalse(report['out_of_scope_observed'])
            self.assertEqual(result['completed'],2)
            state=json.loads(ledger.read_text())
            self.assertTrue(all(r['status']=='settled' for r in state['requests']))
            # Synthetic data in this temporary folder is destroyed, not published
            # as actual model behavior or provider access evidence.
