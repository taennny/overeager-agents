import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scope_lab.batch import prepare_models
from scope_lab.cli import save_json
from scope_lab.model_client import chat, ModelError
from scope_lab.spend_budget import SpendBudget
from tests.test_comparison import fixture
from tests.test_spend_budget import ENV
from scripts.run_defense_comparison_v2 import can_continue_accounted_error


class ErrorAccountingTests(unittest.TestCase):
    def test_nontext_and_truncated_responses_retain_usage_without_thinking_or_keys(self):
        for content,stop in [([{'type':'thinking','thinking':'PRIVATE_THINKING_DO_NOT_LOG'}],'max_tokens'),
                             ([{'type':'text','text':'partial action'}],'max_tokens')]:
            with tempfile.TemporaryDirectory() as d:
                plans,configs,_,_,_=fixture(d)
                class Opener:
                    def open(inner,request,timeout):
                        return io.BytesIO(json.dumps({'model':ENV['CLAUDE_MODEL'],'content':content,'stop_reason':stop,
                          'usage':{'input_tokens':10,'output_tokens':20}}).encode())
                with patch.dict(os.environ,ENV),self.assertRaises(ModelError) as caught:
                    chat(configs['claude'],[{'role':'user','content':'task'}],opener=Opener())
                diagnostics=caught.exception.diagnostics
                self.assertEqual(diagnostics['usage'],{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30})
                self.assertEqual(set(diagnostics),{'usage','model_returned'})
                self.assertNotIn('PRIVATE_THINKING',json.dumps(diagnostics))
                self.assertNotIn(ENV['ANTHROPIC_API_KEY'],json.dumps(diagnostics))

    def test_known_error_is_still_error_but_cost_settles_and_next_cell_can_run(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,_=fixture(d);plan=plans['core'];cell=next(c for c in plan['trials'] if c['profile']=='claude')
            ledger=Path(d)/'ledger.json';budget=SpendBudget(policy,ledger,plan,cfg)
            def failure(*a):raise ModelError('No textual completion',diagnostics={'usage':{'prompt_tokens':10,'completion_tokens':20},'model_returned':ENV['CLAUDE_MODEL']})
            with self.assertRaisesRegex(ModelError,'No textual'):budget.wrap(failure,'claude',cell['trial_id'])([],60)
            state=json.loads(ledger.read_text());row=state['requests'][0]
            self.assertEqual(row['status'],'settled');self.assertEqual(row['response_outcome'],'model_error_with_known_usage')
            self.assertEqual(row['debit_nano_usd'],60_000)
            report={'status':'model_error','agent':{'events':[{'model_diagnostics':{'usage':{'prompt_tokens':10,'completion_tokens':20}}}]}}
            self.assertTrue(can_continue_accounted_error(report,state,cell['trial_id'],'core'))
            self.assertFalse(can_continue_accounted_error(report,state,cell['trial_id'],'preflight'))
            state['requests'][0]['status']='reserved'
            self.assertFalse(can_continue_accounted_error(report,state,cell['trial_id'],'core'))
            other=next(c for c in plan['trials'] if c['profile']=='claude' and c['trial_id']!=cell['trial_id'])
            budget.wrap(lambda *a:{'usage':{'prompt_tokens':1,'completion_tokens':1},'model_returned':ENV['CLAUDE_MODEL']},'claude',other['trial_id'])([],60)

    def test_unknown_or_wrong_model_usage_remains_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,_=fixture(d);plan=plans['core'];cell=next(c for c in plan['trials'] if c['profile']=='gpt')
            budget=SpendBudget(policy,Path(d)/'ledger.json',plan,cfg)
            def failure(*a):raise ModelError('No textual completion',diagnostics={'usage':{},'model_returned':'changed'})
            with self.assertRaises(ModelError):budget.wrap(failure,'gpt',cell['trial_id'])([],60)
            with self.assertRaisesRegex(ModelError,'unresolved'):budget.wrap(lambda *a:self.fail('network'),'gpt',cell['trial_id'])([],60)
            report={'status':'model_error','agent':{'events':[{'model_diagnostics':None}]}}
            self.assertFalse(can_continue_accounted_error(report,{'requests':[]},cell['trial_id'],'core'))

    def test_explicit_uncertain_review_keeps_original_reserved_and_full_debit(self):
        with tempfile.TemporaryDirectory() as d:
            plans,cfg,policy,_,prior=fixture(d)
            cell=next(c for c in plans['core']['trials'] if c['profile']=='claude');amount=145_408_000
            original={'schema_version':'spend-ledger-v0.2','carried_forward_debit_nano_usd':{'gpt':1,'claude':2},
             'requests':[{'request_id':'uncertain','profile':'claude','trial_id':cell['trial_id'],'status':'reserved',
                          'reservation_nano_usd':amount,'debit_nano_usd':amount}]}
            save_json(prior,original)
            report=Path(d)/'failed.json';save_json(report,{'status':'model_error','cell':cell,'agent':{'events':[{'model_error':'No textual completion'}]}})
            data=json.loads(policy.read_text());data.update(schema_version='spend-budget-v0.3')
            data['carryover'].update(ledger_sha256=hashlib.sha256(prior.read_bytes()).hexdigest(),debit_nano_usd={'gpt':1,'claude':amount+2},
               operator_review_evidence='synthetic explicit review; full reservation retained',
               reviewed_uncertain_requests={'uncertain':{'report_path':str(report),'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),
                    'retain_nano_usd':amount,'disposition':'retain_uncertain_full_reservation'}})
            save_json(policy,data)
            budget=SpendBudget(policy,Path(d)/'new-ledger.json',plans['core'],cfg)
            self.assertEqual(budget.carryover,{'gpt':1,'claude':amount+2})
            self.assertEqual(json.loads(prior.read_text()),original)
            data['carryover']['reviewed_uncertain_requests']['uncertain']['retain_nano_usd']=0;save_json(policy,data)
            with self.assertRaisesRegex(ValueError,'operator review'):SpendBudget(policy,Path(d)/'bad-ledger',plans['core'],cfg)
