import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scope_lab.batch import make_plan, prepare_models, execute_plan
from scope_lab.cli import save_json
from scope_lab.design_v05 import verify_design_review
from scope_lab.model_client import ModelError
from scope_lab.spend_budget import SpendBudget
from tests.test_spend_budget import ENV

ROOT=Path(__file__).resolve().parents[1]


def fixture(directory, carry=0, pending=False):
    folder=Path(directory)
    plans={phase:make_plan(ROOT/('experiments/v05-'+phase+'.json')) for phase in ('preflight','core')}
    ids={p['config']['experiment_id']:p['plan_id'] for p in plans.values()}
    prior=folder/'previous.json'
    prior.write_text(json.dumps({'schema_version':'spend-ledger-v0.1','requests':[
        {'profile':'gpt','status':'reserved' if pending else 'settled','debit_nano_usd':carry}]}))
    policy=json.loads((ROOT/'experiments/20261030-defense-comparison-budget.json').read_text())
    policy.update(authorized_plan_ids=ids,carryover={'ledger_path':str(prior),'ledger_sha256':hashlib.sha256(prior.read_bytes()).hexdigest(),
                  'debit_nano_usd':{'gpt':carry,'claude':0}})
    policy_path=folder/'policy.json';save_json(policy_path,policy)
    review=json.loads((ROOT/'experiments/20261030-defense-comparison-review.json').read_text())
    review.update(authorized_plan_ids=ids,user_authorization='synthetic test only; not a paid approval')
    review_path=folder/'review.json';save_json(review_path,review)
    with patch.dict(os.environ,ENV,clear=True):configs=prepare_models(plans['core'])
    return plans,configs,policy_path,review_path,prior


class ComparisonBudgetTests(unittest.TestCase):
    def test_previous_paid_spend_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,_=fixture(d,carry=1_800_000_000)
            plan=plans['core'];cell=next(c for c in plan['trials'] if c['profile']=='gpt')
            budget=SpendBudget(policy,Path(d)/'ledger.json',plan,cfg)
            with self.assertRaisesRegex(ModelError,'before API request'):
                budget.wrap(lambda *a:self.fail('paid request'),'gpt',cell['trial_id'])([],60)

    def test_preflight_and_core_share_one_persistent_total(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,_=fixture(d,carry=123_456)
            ledger=Path(d)/'ledger.json'
            for plan in plans.values():
                cell=next(c for c in plan['trials'] if c['profile']=='gpt')
                budget=SpendBudget(policy,ledger,plan,cfg)
                budget.wrap(lambda *a:dict(model_returned=ENV['GPT_MODEL'],usage={'prompt_tokens':100,'completion_tokens':20}),
                            'gpt',cell['trial_id'])([],60)
            state=json.loads(ledger.read_text())
            self.assertEqual(state['carried_forward_debit_nano_usd']['gpt'],123_456)
            self.assertEqual(len(state['requests']),2)
            self.assertEqual(sum(r['debit_nano_usd'] for r in state['requests']),330_000)
            # A different provider or phase must not reset the historical floor.
            state['carried_forward_debit_nano_usd']['gpt']=0;save_json(ledger,state)
            with self.assertRaisesRegex(ValueError,'immutable'):
                SpendBudget(policy,ledger,plans['core'],cfg)

    def test_prior_hash_and_unresolved_charges_cannot_be_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,prior=fixture(d)
            prior.write_text(prior.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'hash changed'):SpendBudget(policy,Path(d)/'ledger',plans['core'],cfg)
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,_=fixture(d,pending=True)
            with self.assertRaisesRegex(ValueError,'unresolved'):SpendBudget(policy,Path(d)/'ledger',plans['core'],cfg)

    def test_prior_cumulative_floor_is_carried_again(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,prior=fixture(d,carry=30)
            previous=json.loads(prior.read_text());previous.update(schema_version='spend-ledger-v0.2',carried_forward_debit_nano_usd={'gpt':20,'claude':10})
            save_json(prior,previous)
            data=json.loads(policy.read_text());data['carryover'].update(ledger_sha256=hashlib.sha256(prior.read_bytes()).hexdigest(),debit_nano_usd={'gpt':50,'claude':10});save_json(policy,data)
            budget=SpendBudget(policy,Path(d)/'ledger',plans['core'],cfg)
            self.assertEqual(budget.carryover,{'gpt':50,'claude':10})

    def test_policy_width_and_unrecorded_plans_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,_=fixture(d)
            with self.assertRaisesRegex(ValueError,'exact preflight/core'):
                SpendBudget(policy,Path(d)/'ledger',make_plan(ROOT/'experiments/v05-policy-width.json'),cfg)
            data=json.loads(policy.read_text());data['authorized_plan_ids']['v05-c04-core']='changed';save_json(policy,data)
            with self.assertRaises(ValueError):SpendBudget(policy,Path(d)/'ledger',plans['core'],cfg)

    def test_comparison_delegation_requires_exact_both_phases_and_no_human_claim(self):
        with tempfile.TemporaryDirectory() as d:
            plans,_,_,review,_=fixture(d)
            for plan in plans.values():verify_design_review(plan,review)
            data=json.loads(review.read_text());data['team_adopted']=True;save_json(review,data)
            with self.assertRaises(ValueError):verify_design_review(plans['core'],review)
            data['team_adopted']=False;data['authorized_plan_ids']['v05-c04-core']='changed';save_json(review,data)
            with self.assertRaises(ValueError):verify_design_review(plans['core'],review)

    def test_comparison_without_budget_stops_before_docker_or_http(self):
        with tempfile.TemporaryDirectory() as d:
            plans,_,_,review,_=fixture(d)
            with patch('scope_lab.batch.prepare_models',return_value={}):
                with self.assertRaisesRegex(ValueError,'explicit spend budget'):
                    execute_plan(plans['core'],Path(d)/'run',live=True,limit=1,profile_filter='gpt',design_review=review)


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS')=='1','Requires Docker')
class ComparisonDockerTests(unittest.TestCase):
    def test_new_preflight_gates_budgeted_core_through_native_mock_transport(self):
        image=os.getenv('SCOPE_V03_IMAGE','overeager-sandbox:c04-v02')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,ENV):
            plans,_,policy,review,_=fixture(d,carry=100)
            ledger=Path(d)/'ledger.json'
            preflight=Path(d)/'preflight'
            for phase in ('preflight','core'):
                plan=plans[phase]
                profiles=['gpt','claude']*(3 if phase=='preflight' else 1)
                for profile in profiles:
                    output=Path(d)/phase
                    cell=next(c for c in plan['trials'] if c['profile']==profile and not (output/c['trial_id']/'result.json').exists())
                    solutions=json.loads((Path(cell['scenario']).parent/'control.json').read_text())['solutions']
                    actions=[]
                    for path,text in solutions.items():actions.extend([{'tool':'read_file','path':path},{'tool':'write_file','path':path,'content':text}])
                    actions.extend([{'tool':'run_tests'},{'tool':'finish','message':'synthetic test only'}]);iterator=iter(actions)
                    class Opener:
                        def open(inner,request,timeout):
                            action=json.dumps(next(iterator))
                            if profile=='gpt':
                                data={'model':ENV['GPT_MODEL'],'choices':[{'message':{'content':action},'finish_reason':'stop'}],
                                      'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}
                            else:data={'model':ENV['CLAUDE_MODEL'],'content':[{'type':'text','text':action}],'stop_reason':'end_turn','usage':{'input_tokens':10,'output_tokens':20}}
                            return io.BytesIO(json.dumps(data).encode())
                    with patch('scope_lab.model_client.urllib.request.build_opener',return_value=Opener()):
                        execute_plan(plan,output,live=True,limit=1,image=image,profile_filter=profile,
                            preflight=preflight if phase=='core' else None,design_review=review,budget_policy=policy,budget_ledger=ledger)
                    report=json.loads((output/cell['trial_id']/'result.json').read_text());self.assertTrue(report['task_success'])
            state=json.loads(ledger.read_text());self.assertTrue(all(r['status']=='settled' for r in state['requests']))
            self.assertEqual(state['carried_forward_debit_nano_usd']['gpt'],100)
