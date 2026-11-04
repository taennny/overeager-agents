import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.baseline_extension import (CONFIG, DECISION, ContinuationBudget,
    MODELS, RATES, validate_plan, verify_legacy, prior_floor)
from scope_lab.batch import make_plan, prepare_models, digest
from scope_lab.cli import save_json
from scope_lab.harness import run
from scope_lab.model_client import ModelError, make_completion, inference_metadata
from tests.test_spend_budget import ENV

ROOT=Path(__file__).resolve().parents[1]


def data():
    plan=make_plan(CONFIG);decision=json.loads(DECISION.read_text())
    decision['plan_id']=plan['plan_id'];decision['budget']['plan_id']=plan['plan_id']
    with patch.dict(os.environ,ENV):configs=prepare_models(plan)
    return plan,decision,configs


class BaselineExtensionTests(unittest.TestCase):
    def test_balanced_54_new_and_archived_six_have_matching_inputs_and_scorer(self):
        plan,decision,_=data();new=validate_plan(plan,decision);legacy=verify_legacy(plan,decision)
        self.assertEqual(len(new),54);self.assertEqual(len(legacy),6)
        for model in MODELS:
            selected=[c for c in new if c['profile']==model]
            self.assertEqual(len(selected),27)
            for task in {c['scenario_id'] for c in selected}:
                self.assertEqual(sorted(c['repeat'] for c in selected if c['scenario_id']==task),list(range(1,10)))
        bad=copy.deepcopy(plan);bad['config']['defenses']=['D2']
        with self.assertRaises(ValueError):validate_plan(bad,decision)
        bad=copy.deepcopy(decision);bad['legacy_reports'][1]=bad['legacy_reports'][0]
        with self.assertRaises(ValueError):verify_legacy(plan,bad)

    def test_reserve_precedes_http_and_known_usage_settles(self):
        plan,decision,configs=data();cell=next(c for c in plan['trials'] if c['profile']=='gpt' and c['repeat']>0)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ledger.json';budget=ContinuationBudget(path,decision['budget'],plan,configs,{'gpt':100,'claude':200})
            def answer(*args):
                row=json.loads(path.read_text())['requests'][0]
                self.assertEqual(row['status'],'in_flight');self.assertEqual(row['debit_nano_usd'],119808000)
                return {'model_returned':MODELS['gpt'],'usage':{'prompt_tokens':100,'completion_tokens':20}}
            budget.wrap(answer,'gpt',cell['trial_id'])([],60)
            row=json.loads(path.read_text())['requests'][0];self.assertEqual(row['status'],'settled');self.assertEqual(row['debit_nano_usd'],165000)
            self.assertNotIn(ENV['OPENAI_API_KEY'],path.read_text())

    def test_closed_timeout_retains_full_charge_and_next_distinct_trial_runs(self):
        plan,decision,configs=data();cells=[c for c in plan['trials'] if c['profile']=='claude' and c['repeat']>0]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ledger.json';budget=ContinuationBudget(path,decision['budget'],plan,configs,{'gpt':0,'claude':500479000})
            def failure(*args):raise ModelError('API connection failed or timed out')
            with self.assertRaises(ModelError):budget.wrap(failure,'claude',cells[0]['trial_id'])([],60)
            state=json.loads(path.read_text());self.assertEqual(state['requests'][0]['status'],'uncertain_retained')
            self.assertEqual(state['requests'][0]['debit_nano_usd'],145408000)
            budget.wrap(lambda *a:{'model_returned':MODELS['claude'],'usage':{'prompt_tokens':1,'completion_tokens':1}},'claude',cells[1]['trial_id'])([],60)
            state=json.loads(path.read_text());self.assertEqual(len(state['requests']),2)
            self.assertEqual(state['carried_forward_debit_nano_usd']['claude'],500479000)

    def test_crash_in_flight_blocks_another_paid_call(self):
        plan,decision,configs=data();cells=[c for c in plan['trials'] if c['profile']=='gpt' and c['repeat']>0]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ledger.json';budget=ContinuationBudget(path,decision['budget'],plan,configs,{'gpt':0,'claude':0})
            def crash(*a):raise RuntimeError('synthetic crash')
            with self.assertRaises(RuntimeError):budget.wrap(crash,'gpt',cells[0]['trial_id'])([],60)
            with self.assertRaisesRegex(ModelError,'in_flight'):
                budget.wrap(lambda *a:self.fail('paid retry'),'gpt',cells[1]['trial_id'])([],60)
            self.assertEqual(json.loads(path.read_text())['requests'][0]['status'],'in_flight')

    def test_cumulative_cap_and_unknown_request_limit_block_before_http(self):
        plan,decision,configs=data();cells=[c for c in plan['trials'] if c['profile']=='claude' and c['repeat']>0]
        with tempfile.TemporaryDirectory() as d:
            budget=ContinuationBudget(Path(d)/'ledger.json',decision['budget'],plan,configs,{'gpt':0,'claude':1800000000})
            with self.assertRaisesRegex(ModelError,'spend_cap'):budget.wrap(lambda *a:self.fail('paid HTTP'),'claude',cells[0]['trial_id'])([],60)
        with tempfile.TemporaryDirectory() as d:
            budget=ContinuationBudget(Path(d)/'ledger.json',decision['budget'],plan,configs,{'gpt':0,'claude':0})
            def timeout(*a):raise ModelError('synthetic timeout')
            for cell in cells[:4]:
                with self.assertRaises(ModelError):budget.wrap(timeout,'claude',cell['trial_id'])([],60)
            with self.assertRaisesRegex(ModelError,'uncertain_request_limit'):
                budget.wrap(lambda *a:self.fail('paid HTTP'),'claude',cells[4]['trial_id'])([],60)

    def test_wrong_identity_known_error_and_tampered_floor(self):
        plan,decision,configs=data();cell=next(c for c in plan['trials'] if c['profile']=='gpt' and c['repeat']>0)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ledger.json';budget=ContinuationBudget(path,decision['budget'],plan,configs,{'gpt':0,'claude':0})
            def failed(*a):raise ModelError('No textual completion',diagnostics={'model_returned':MODELS['gpt'],'usage':{'prompt_tokens':10,'completion_tokens':20}})
            with self.assertRaises(ModelError):budget.wrap(failed,'gpt',cell['trial_id'])([],60)
            self.assertEqual(json.loads(path.read_text())['requests'][0]['status'],'settled')
            state=json.loads(path.read_text());state['carried_forward_debit_nano_usd']['gpt']=-1;save_json(path,state)
            with self.assertRaisesRegex(ValueError,'changed'):ContinuationBudget(path,decision['budget'],plan,configs,{'gpt':0,'claude':0})
        with tempfile.TemporaryDirectory() as d:
            budget=ContinuationBudget(Path(d)/'ledger.json',decision['budget'],plan,configs,{'gpt':0,'claude':0})
            with self.assertRaises(ModelError):budget.wrap(lambda *a:{'model_returned':'wrong','usage':{'prompt_tokens':1,'completion_tokens':1}},'gpt',cell['trial_id'])([],60)
            self.assertEqual(budget.stopped(),'changed_model_identity')


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS')=='1','Requires Docker')
class BaselineExtensionDockerTests(unittest.TestCase):
    def test_same_harness_grades_mock_native_transports_with_extension_budget(self):
        plan,decision,configs=data();image=os.getenv('SCOPE_V03_IMAGE','overeager-sandbox:c04-v02')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV):
            budget=ContinuationBudget(Path(d)/'ledger.json',decision['budget'],plan,configs,{'gpt':0,'claude':0})
            for profile in MODELS:
                cell=next(c for c in plan['trials'] if c['profile']==profile and c['repeat']>0)
                control=json.loads((Path(cell['scenario']).parent/'control.json').read_text());actions=[]
                for name,text in control['solutions'].items():actions.extend([{'tool':'read_file','path':name},{'tool':'write_file','path':name,'content':text}])
                actions.extend([{'tool':'run_tests'},{'tool':'finish','message':'synthetic control'}]);it=iter(actions)
                class Opener:
                    def open(inner,request,timeout):
                        action=json.dumps(next(it))
                        if profile=='gpt':value={'model':MODELS[profile],'choices':[{'message':{'content':action},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}
                        else:value={'model':MODELS[profile],'content':[{'type':'text','text':action}],'stop_reason':'end_turn','usage':{'input_tokens':10,'output_tokens':20}}
                        return io.BytesIO(json.dumps(value).encode())
                with patch('scope_lab.model_client.urllib.request.build_opener',return_value=Opener()):
                    report=run(cell['scenario'],Path(d)/profile,budget.wrap(make_completion(configs[profile]),profile,cell['trial_id']),'llm',image,24,300,
                        inference_metadata(configs[profile],profile),'D0',json.loads(Path(cell['policy_path']).read_text()),approval_mode='scope_simulated',prompt_variant='environment-v2')
                self.assertTrue(report['task_success']);self.assertFalse(report['out_of_scope_observed'])
