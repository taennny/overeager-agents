import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scope_lab.api_pilot import check
from scope_lab.batch import make_plan, execute_plan, prepare_models, validate_api_preflight
from scope_lab.model_client import chat, inference_metadata, ModelError

ROOT = Path(__file__).resolve().parents[1]
ENV = {'OPENAI_API_KEY': 'fake-gpt-only', 'GPT_MODEL': 'test-gpt',
       'ANTHROPIC_API_KEY': 'fake-claude-only', 'CLAUDE_MODEL': 'test-claude',
       'GPT_BASE_URL': 'https://api.openai.com/v1', 'CLAUDE_BASE_URL': 'https://api.anthropic.com/v1'}


class ApiPilotTests(unittest.TestCase):
    def test_matrices_share_assets_without_duplicate_baselines(self):
        plans = {p: make_plan(ROOT/('experiments/api-'+p+'.json')) for p in ('smoke','preflight','pilot')}
        self.assertEqual([len(p['trials']) for p in plans.values()], [2,6,48])
        pilot = plans['pilot']
        self.assertEqual(sum(c['defense']=='D0' for c in pilot['trials']), 6)
        self.assertEqual(sum(c['defense']=='D1' for c in pilot['trials']), 6)
        local = make_plan(ROOT/'experiments/v04-preflight.json')
        self.assertEqual({c['fingerprint'] for c in local['trials']}, {c['fingerprint'] for c in pilot['trials']})
        self.assertEqual({c['profile'] for c in pilot['trials']}, {'claude','gpt'})

    def test_offline_check_without_keys_or_network(self):
        with patch.dict(os.environ, {}, clear=True), patch('urllib.request.build_opener', side_effect=AssertionError('network')):
            report = check()
        self.assertEqual(len(report['missing_environment']), 4)
        self.assertEqual(report['live_requests'], 0)
        with patch.dict(os.environ, ENV, clear=True):
            report = check()
        self.assertEqual(report['status'], 'configured_not_live_verified')
        self.assertNotIn('fake-', json.dumps(report))

    def test_native_protocols_keep_declared_limits_and_defaults(self):
        with patch.dict(os.environ, ENV, clear=True):
            configs = prepare_models(make_plan(ROOT/'experiments/api-preflight.json'))
            for profile, cfg in configs.items():
                class Opener:
                    def open(inner, request, timeout):
                        body=json.loads(request.data)
                        self.assertNotIn('temperature', body)
                        self.assertNotIn('format', body)
                        self.assertNotIn('num_ctx', body)
                        if profile=='gpt':
                            self.assertEqual(body['max_completion_tokens'],4096)
                            result={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
                        else:
                            self.assertEqual(body['max_tokens'],4096)
                            self.assertEqual(body['system'],'system')
                            result={'content':[{'type':'text','text':'{}'}],'stop_reason':'end_turn'}
                        return io.BytesIO(json.dumps(result).encode())
                chat(cfg,[{'role':'system','content':'system'},{'role':'user','content':'task'}],max_tokens=4096,opener=Opener())
                self.assertEqual(inference_metadata(cfg,profile)['sampling'],'provider-default')

    def test_request_size_stops_before_paid_http(self):
        with patch.dict(os.environ, ENV, clear=True):
            cfg=prepare_models(make_plan(ROOT/'experiments/api-preflight.json'))['gpt']
            class Opener:
                def open(*args,**kwargs): raise AssertionError('paid call')
            with self.assertRaisesRegex(ModelError, 'byte budget'):
                chat(cfg,[{'role':'user','content':'x'*140000}],opener=Opener())

    def test_no_bulk_api_calls_or_missing_profile(self):
        plan=make_plan(ROOT/'experiments/api-smoke.json')
        for limit,profile in [(2,'gpt'),(1,None)]:
            with self.assertRaisesRegex(ValueError,'one trial'):
                execute_plan(plan,'unused',live=True,limit=limit,profile_filter=profile)
        with self.assertRaisesRegex(ValueError,'--live'):
            execute_plan(plan,'unused',limit=1,profile_filter='gpt')

    def test_api_configs_reject_ollama_and_retries(self):
        source=ROOT/'experiments/api-preflight.json'
        for field,value in [('profiles',['qwen','exaone']),('max_retries',1),('max_steps',100)]:
            cfg=json.loads(source.read_text());cfg[field]=value
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'bad.json';p.write_text(json.dumps(cfg))
                with self.assertRaisesRegex(ValueError,'Claude/GPT'):
                    make_plan(p)
        with patch.dict(os.environ,dict(ENV,GPT_BASE_URL='https://example.invalid/v1'),clear=True):
            with self.assertRaisesRegex(ValueError,'official'):
                prepare_models(make_plan(source))

    def test_expansion_rechecks_source_results_and_identity(self):
        baseline=make_plan(ROOT/'experiments/api-preflight.json')
        pilot=make_plan(ROOT/'experiments/api-pilot.json')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            lock={'plan':baseline,'models':{},'image_id':'image','implementation_hash':'code'}
            (root/'plan.json').write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError,'incomplete or failed'):
                validate_api_preflight(pilot,root,{},'image','code')
            for cell in baseline['trials']:
                p=root/cell['trial_id'];p.mkdir()
                (p/'result.json').write_text(json.dumps(dict(cell=cell,status='finished',trial_valid=True,
                    observation_valid=True,task_success=True,out_of_scope_observed=False,evidence_type='llm')))
            validate_api_preflight(pilot,root,{},'image','code')
            with self.assertRaisesRegex(ValueError,'differ'):
                validate_api_preflight(pilot,root,{},'image','changed-code')
            with self.assertRaisesRegex(ValueError,'differ'):
                validate_api_preflight(pilot,root,{'gpt':{}},'image','code')
            p=root/baseline['trials'][0]['trial_id']/'result.json'
            report=json.loads(p.read_text());report['task_success']=False;p.write_text(json.dumps(report))
            (root/'readiness.json').write_text('{"compatibility_gate":"ready_for_team_review"}')
            with self.assertRaisesRegex(ValueError,'incomplete or failed'):
                validate_api_preflight(pilot,root,{},'image','code')


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS')=='1','Requires Docker')
class ApiDockerTests(unittest.TestCase):
    def test_native_mock_http_through_docker_and_oracle(self):
        plan=make_plan(ROOT/'experiments/api-smoke.json')
        image=os.getenv('SCOPE_V03_IMAGE','overeager-sandbox:week1')
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,ENV):
            for profile in ('claude','gpt'):
                control=json.loads((Path(plan['trials'][0]['scenario']).parent/'control.json').read_text())
                actions=[]
                for path,content in control['solutions'].items():
                    actions.extend([{'tool':'read_file','path':path},{'tool':'write_file','path':path,'content':content}])
                actions.extend([{'tool':'run_tests'},{'tool':'finish','message':'mock transport control'}])
                iterator=iter(actions)
                class Opener:
                    def open(inner,request,timeout):
                        action=json.dumps(next(iterator))
                        if profile=='claude':
                            value={'model':'test-claude','content':[{'type':'text','text':action}],
                                   'stop_reason':'end_turn','usage':{'input_tokens':10,'output_tokens':10}}
                        else:
                            value={'model':'test-gpt','choices':[{'message':{'content':action},'finish_reason':'stop'}],
                                   'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
                        return io.BytesIO(json.dumps(value).encode())
                with patch('scope_lab.model_client.urllib.request.build_opener',return_value=Opener()):
                    result=execute_plan(plan,d,live=True,limit=1,image=image,profile_filter=profile)
                    self.assertEqual(result['executed_this_invocation'],1)
                cell=next(c for c in plan['trials'] if c['profile']==profile)
                report=json.loads((Path(d)/cell['trial_id']/'result.json').read_text())
                self.assertTrue(report['task_success'])
                self.assertFalse(report['out_of_scope_observed'])
                self.assertNotIn('fake-',json.dumps(report))
            # Temporary mock HTTP artifacts are never retained as live-model evidence.
            self.assertEqual(result['completed'],2)
