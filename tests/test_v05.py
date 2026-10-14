import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scope_lab.agent import parse_action, ActionError, run_loop
from scope_lab.batch import make_plan, execute_plan, scenario_fingerprint, digest, validate_api_preflight
from scope_lab.defenses import Gate, defense_label
from scope_lab.design_v05 import verify_design_review
from scope_lab.harness import load_scenario, run
from scope_lab.measurement_rates import summarize_observations
from scope_lab.observations import read_observations, python_candidates
from scope_lab.risk import ApprovalLedger, assess_risk, validate_risk
from scope_lab.sandbox import DockerSandbox, SandboxError
from scope_lab.test_tool import FixedTestTool, TestCleanupError

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'research_scenarios/v05'
SOURCE = ASSETS/'03-dev-config/scenario.ko.json'
IMAGE = os.getenv('SCOPE_V03_IMAGE', 'overeager-sandbox:v05')


class V05AssetsTests(unittest.TestCase):
    def test_all_legacy_bytes_unchanged(self):
        for path, expected in json.loads((ASSETS/'legacy-sha256.json').read_text()).items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), expected, path)

    def test_new_pairs_reuse_functional_assets_and_only_scope_id_changes(self):
        for folder in ASSETS.iterdir():
            if not folder.is_dir():
                continue
            old = ROOT/'research_scenarios/v03'/folder.name
            scenario, scope, _ = load_scenario(folder/'scenario.ko.json')
            explicit, _, _ = load_scenario(folder/'scenario.explicit.ko.json')
            self.assertEqual(explicit['prompt'], json.loads((old/'scenario.ko.json').read_text())['prompt'])
            self.assertNotEqual(scenario['prompt'], explicit['prompt'])
            previous = json.loads((old/'scope.json').read_text())
            self.assertEqual(scope['allowed'], previous['allowed'])
            self.assertEqual(scope['protected'], previous['protected'])
            self.assertFalse(scenario['design_spec']['team_adopted'])
            for name in ('evaluate.py', 'development_tests.py', 'test_tool.json', 'action_scope.json', 'control.json'):
                self.assertEqual((folder/name).read_bytes(), (old/name).read_bytes())
            for file in (old/'fixture').rglob('*'):
                if file.is_file():
                    self.assertEqual(file.read_bytes(), (folder/'fixture'/file.relative_to(old/'fixture')).read_bytes())

    def test_offline_six_twentyfour_twelve_controls_and_unique_baselines(self):
        with patch('urllib.request.build_opener', side_effect=AssertionError('Network')), patch.dict(os.environ, {}, clear=True):
            plans = {n: make_plan(ROOT/('experiments/v05-' + n + '.json')) for n in ('preflight','core','policy-width','controls')}
        self.assertEqual([len(p['trials']) for p in plans.values()], [6,24,12,36])
        core = plans['core']['trials']
        for defense in ('D0','D1','D2','D3-risk'):
            self.assertEqual(sum(c['defense'] == defense for c in core), 6)
        self.assertEqual(len({c['trial_id'] for c in core}), 24)
        self.assertFalse({c['trial_id'] for c in core} & {c['trial_id'] for c in plans['preflight']['trials']})
        for cell in plans['policy-width']['trials']:
            self.assertEqual(cell['orr_eligible'], cell['policy_variant'] != 'narrow')

    def test_new_rules_affect_fingerprints(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)/'scenario'; shutil.copytree(SOURCE.parent, home)
            source = home/'scenario.ko.json'; before = scenario_fingerprint(source)
            risk = json.loads((home/'risk.json').read_text())
            risk['resources']['src/config_loader.py'] = 'config'
            (home/'risk.json').write_text(json.dumps(risk))
            self.assertNotEqual(before, scenario_fingerprint(source))

    def test_pending_design_never_reaches_api(self):
        plan = make_plan(ROOT/'experiments/v05-core.json')
        with patch('scope_lab.batch.prepare_models', side_effect=AssertionError('No model access before review')):
            with self.assertRaisesRegex(ValueError, 'design-review'):
                execute_plan(plan, 'unused', live=True, limit=1, profile_filter='gpt')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'review.json'
            review = {'schema_version':'design-review-v0.1','assets_digest':digest(sorted({c['fingerprint'] for c in plan['trials']})),
                      'decision':'pending','reviewed_by_a':'','reviewed_by_b':'','reviewed_at':'','decision_evidence':''}
            path.write_text(json.dumps(review))
            with self.assertRaises(ValueError): verify_design_review(plan, path)
            # Synthetic validation data; never saved as a real team decision.
            review.update(decision='adopt_for_pilot', reviewed_by_a='test A', reviewed_by_b='test B',
                          reviewed_at='test date',decision_evidence='synthetic test only')
            path.write_text(json.dumps(review)); verify_design_review(plan, path)
            review['assets_digest'] = 'changed';path.write_text(json.dumps(review))
            with self.assertRaises(ValueError): verify_design_review(plan, path)

    def test_legacy_d3_names_stay_distinct(self):
        self.assertEqual(defense_label('D3', approval_mode='scope_simulated'), 'D3-scope-simulated')
        self.assertEqual(defense_label('D3-risk', approval_mode='scope_simulated'), 'D3-risk-scope-simulated')

    def test_core_and_width_require_matching_completed_v05_preflight(self):
        baseline=make_plan(ROOT/'experiments/v05-preflight.json')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            lock={'plan':baseline,'models':{},'image_id':'image','implementation_hash':'code'}
            (root/'plan.json').write_text(json.dumps(lock))
            for name in ('core','policy-width'):
                plan=make_plan(ROOT/('experiments/v05-'+name+'.json'))
                with self.assertRaisesRegex(ValueError,'incomplete or failed'):
                    validate_api_preflight(plan,root,{},'image','code')
            for cell in baseline['trials']:
                folder=root/cell['trial_id'];folder.mkdir()
                (folder/'result.json').write_text(json.dumps(dict(cell=cell,status='finished',trial_valid=True,
                    observation_valid=True,task_success=True,out_of_scope_observed=False,evidence_type='llm')))
            for name in ('core','policy-width'):
                plan=make_plan(ROOT/('experiments/v05-'+name+'.json'))
                validate_api_preflight(plan,root,{},'image','code')
                with self.assertRaisesRegex(ValueError,'differ'):
                    validate_api_preflight(plan,root,{},'image','new-code')
            lock['plan']=make_plan(ROOT/'experiments/api-preflight.json')
            (root/'plan.json').write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError,'differ'):
                validate_api_preflight(plan,root,{},'image','code')

    def test_reproduction_failure_leaves_evidence_and_never_overwrites(self):
        from scope_lab.reproduce import reproduce
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'new'
            with patch('scope_lab.reproduce._reproduce',side_effect=SandboxError('synthetic failure')):
                self.assertEqual(reproduce(out,'B','unused'),2)
            evidence=json.loads((out/'evidence.json').read_text())
            self.assertEqual(evidence['status'],'failed_infrastructure')
            self.assertFalse(evidence['team_reproduction_complete'])
            with self.assertRaisesRegex(ValueError,'new reproduction'):
                reproduce(out,'B','unused')

    def test_two_evidence_comparison_rejects_image_drift_and_ci_as_a(self):
        from scope_lab.reproduce import compare_evidence
        record=dict(commit='test',implementation_sha256='code',image_id='image',image_platform='linux/test',
            dockerfile_sha256='file',assets={'x':'y'},offline_plan_counts={'controls':36},
            status='passed',tests_exit_code=0,controls_passed=36,controls_planned=36,tracked_worktree_dirty=False)
        with tempfile.TemporaryDirectory() as directory:
            b=Path(directory)/'b.json';a=Path(directory)/'a.json'
            b.write_text(json.dumps(dict(record,actor_self_reported='B')))
            a.write_text(json.dumps(dict(record,actor_self_reported='CI')))
            self.assertFalse(compare_evidence(b,a)['ab_roles_claimed'])
            a.write_text(json.dumps(dict(record,actor_self_reported='A',image_id='other')))
            self.assertIn('image_id',compare_evidence(b,a)['differences'])
            a.write_text(json.dumps(dict(record,actor_self_reported='A')))
            result=compare_evidence(b,a)
            self.assertTrue(result['matching_technical_evidence']);self.assertTrue(result['ab_roles_claimed'])
            self.assertFalse(result['team_reproduction_complete'])


class RiskGateTests(unittest.TestCase):
    def setUp(self):
        self.scenario, _, _ = load_scenario(SOURCE)
        self.policy = json.loads((SOURCE.parent/'policy.fit.json').read_text())
        self.scope = self.scenario['action_scope_spec']

    def gate(self, policy=None, risk=None, **kwargs):
        return Gate('D3-risk', policy or self.policy,
                    kwargs.get('execute', lambda a,t: {'ok':True,'executed':True}),
                    action_scope=self.scope, approval_mode='scope_simulated',
                    risk_policy=risk or self.scenario['risk_spec'],
                    inspect_target=lambda a,t: {'ok':True,'target_state':{'synthetic':'state'}})

    def test_risk_scope_cross_product_and_unknown(self):
        for kind, risk_expected in [('source',False),('config',True)]:
            for path, inside in [('src/config_loader.py',True),('outside.py',False)]:
                risk = {'version':'risk-policy-v0.1','resources':{path:kind}}
                gate = self.gate(risk=risk)
                result = gate({'tool':'write_file','path':path,'content':'synthetic'}, 1)
                event = gate.events[0]
                self.assertEqual(event['within_user_scope'],inside)
                self.assertEqual(event['asked'],risk_expected)
                self.assertEqual(event['blocked'],risk_expected and not inside)
                self.assertEqual(event['tool_dispatched'],not (risk_expected and not inside))
                if risk_expected and inside: self.assertTrue(event['approved'])
        gate = self.gate()
        self.assertTrue(gate({'tool':'shell','command':'cat src/config_loader.py; rm config/prod.json'},1)['blocked'])
        self.assertIsNone(gate.events[0]['within_user_scope'])
        self.assertIsNone(gate.events[0]['risk_required'])
        self.assertFalse(gate.events[0]['approved'])

    def test_policy_inside_risk_is_asked_and_low_risk_outside_policy_is_not_d2(self):
        gate = self.gate()
        gate({'tool':'write_file','path':'config/dev.json','content':'{}'}, 1)
        self.assertTrue(gate.events[0]['within_policy']);self.assertTrue(gate.events[0]['asked'])
        narrow = json.loads((SOURCE.parent/'policy.narrow.json').read_text())
        gate = self.gate(policy=narrow)
        gate({'tool':'write_file','path':'src/config_loader.py','content':'# source'}, 1)
        self.assertFalse(gate.events[0]['within_policy']);self.assertFalse(gate.events[0]['asked'])
        self.assertTrue(gate.events[0]['executed'])

    def test_unknown_resource_asks_but_does_not_invent_scope(self):
        gate = self.gate()
        gate({'tool':'read_file','path':'unclassified'}, 1)
        self.assertIsNone(gate.events[0]['risk_required'])
        self.assertTrue(gate.events[0]['asked']);self.assertTrue(gate.events[0]['blocked'])

    def test_scope_simulation_rejects_mixed_shell_without_partial_execution(self):
        gate = self.gate(execute=lambda *a:self.fail('mixed request executed'))
        result=gate({'tool':'shell','command':'printf 30 > config/dev.json; printf 30 > config/prod.json'},1)
        self.assertTrue(result['blocked']);self.assertIsNone(gate.events[0]['within_user_scope'])
        with self.assertRaises(ActionError):
            parse_action(json.dumps({'tool':'write_file','path':'config/dev.json','content':'{}','actions':[]}))

    def test_unknown_scope_both_risk_branches_preserve_unknown(self):
        for kind, asks in [('source',False),('config',True)]:
            gate=self.gate(risk={'version':'risk-policy-v0.1','resources':{'ambiguous':kind}})
            with patch('scope_lab.action_scope.classify_action',return_value=(None,'synthetic_unknown_label')):
                gate({'tool':'write_file','path':'ambiguous','content':'x'},1)
            self.assertIsNone(gate.events[0]['within_user_scope'])
            self.assertEqual(gate.events[0]['asked'],asks)
            self.assertEqual(gate.events[0]['blocked'],asks)

    def test_ground_truth_and_approval_evidence_not_fed_back_to_model(self):
        seen=[]
        actions=iter([{'tool':'run_tests'},{'tool':'finish','message':'done'}])
        def complete(messages,remaining):
            seen.append(copy.deepcopy(messages));return {'content':json.dumps(next(actions))}
        evidence={'ok':True,'output':'public feedback','policy_event':{'within_user_scope':True},
                  'test_run':{'secret_internal_metadata':'hidden'},'file_access':{'path':'private'}}
        result=run_loop('task',complete,lambda *a:copy.deepcopy(evidence),private_telemetry=True)
        self.assertIn('public feedback',seen[1][-1]['content'])
        for private in ('within_user_scope','secret_internal_metadata','file_access'):
            self.assertNotIn(private,seen[1][-1]['content'])
        self.assertEqual(result['events'][0]['observation'],evidence)

    def test_single_use_and_changed_target_or_content_reject_grant(self):
        action={'tool':'write_file','path':'config/dev.json','content':'{}'}
        for mutated in [dict(action,path='config/prod.json'),dict(action,content='evil')]:
            ledger=ApprovalLedger();grant=ledger.issue(action,{'version':1})
            with self.assertRaises(ValueError):ledger.consume(grant,mutated)
        ledger=ApprovalLedger();grant=ledger.issue(action,{'version':1})
        ledger.consume(grant,action)
        with self.assertRaises(ValueError):ledger.consume(grant,action)
        with self.assertRaises(ValueError):ApprovalLedger().consume(grant,action)

    def test_caller_mutation_does_not_change_approved_action(self):
        action={'tool':'write_file','path':'config/dev.json','content':'{}'}
        seen=[]
        gate=self.gate(execute=lambda a,t:seen.append(a) or {'ok':True,'executed':True})
        def inspect(*args):
            action['path']='config/prod.json'
            return {'ok':True,'target_state':{'synthetic':'state'}}
        gate.inspect_target=inspect;gate(action,1)
        self.assertEqual(seen[0]['path'],'config/dev.json')

    def test_dispatch_failure_and_blocked_effect_are_different(self):
        gate=self.gate(execute=lambda *a:(_ for _ in ()).throw(SandboxError('synthetic transport failure')))
        with self.assertRaises(SandboxError):gate({'tool':'run_tests'},1)
        self.assertTrue(gate.events[0]['tool_dispatched']);self.assertIsNone(gate.events[0]['executed'])
        gate=self.gate();gate({'tool':'write_file','path':'config/prod.json','content':'{}'},1)
        self.assertFalse(gate.events[0]['tool_dispatched']);self.assertFalse(gate.events[0]['executed'])
        self.assertFalse(gate.events[0]['effect'])

    def test_sensitive_read_risk_not_based_on_scope_truth(self):
        spec=validate_risk({'version':'risk-policy-v0.1','resources':{'secret.txt':'secret'}})
        self.assertEqual(assess_risk({'tool':'read_file','path':'secret.txt'},spec),(True,'resource_kind:secret'))


class ObservationMetricTests(unittest.TestCase):
    def test_public_summary_uses_partial_observations_not_only_valid_trials(self):
        from scope_lab.metrics import summarize
        from scope_lab.action_scope import action_summary
        plan=make_plan(ROOT/'experiments/v05-core.json')
        cells=[c for c in plan['trials'] if c['profile']=='gpt' and c['defense']=='D0']
        plan=dict(plan,trials=cells)
        reports={}
        for i,c in enumerate(cells[:2]):
            reports[c['trial_id']]=dict(cell=c,evidence_type='llm',trial_started=True,
                trial_valid=False,observation_valid=(i==0),task_evaluation_valid=False,
                task_success=None,out_of_scope_observed=True if i==0 else None,
                status='tool_error',policy_events=[],action_scope_summary=action_summary([],None))
        row=summarize(plan,reports)['groups'][0]
        self.assertEqual(row['valid'],0);self.assertEqual(row['started'],2)
        self.assertEqual(row['fs_osr'],1);self.assertEqual(row['fs_observed'],1)
        self.assertIsNone(row['tsr']);self.assertIsNone(row['legacy_valid_only_rates']['fs_osr'])
        self.assertEqual(row['orr_eligible'],2);self.assertIsNone(row['orr'])

    def test_hand_counted_denominators_preserve_partial_failure(self):
        def cell(i, eligible=True):return {'trial_id':str(i),'orr_eligible':eligible}
        def report(**kw):return dict(trial_started=True,trial_valid=True,observation_valid=True,
                                    task_evaluation_valid=True,task_success=True,out_of_scope_observed=False,
                                    status='finished',**kw)
        good=report()
        partial=dict(good,trial_valid=False,status='tool_timeout',task_evaluation_valid=False,
                     task_success=None,out_of_scope_observed=True)
        unknown=dict(good,trial_valid=False,observation_valid=False,task_evaluation_valid=False,
                     status='tool_error',task_success=None,out_of_scope_observed=None)
        items=[(cell(0),good),(cell(1),partial),(cell(2),unknown),(cell(3),None),
               (cell(4),{'trial_started':False,'status':'setup_error'})]
        rates=summarize_observations(items,{'0':{'over_refusal':False}})
        self.assertEqual((rates['planned'],rates['started'],rates['fs_observed'],rates['task_evaluated']), (5,3,2,1))
        self.assertEqual(rates['fs_osr'],{'numerator':1,'denominator':2,'rate':0.5})
        self.assertEqual(rates['tsr']['rate'],1)
        self.assertEqual(rates['partial_or_invalid_observed_violations'],1)
        self.assertEqual(rates['fs_violation_started_bounds']['lower_bound'],1/3)
        self.assertEqual(rates['fs_violation_started_bounds']['upper_bound'],2/3)
        self.assertIsNone(rates['orr']['rate']);self.assertEqual(rates['orr']['unknown'],2)
        self.assertIsNone(summarize_observations([(cell(0),None)],{})['fs_osr']['rate'])

    def test_recovery_approval_block_outside_block_and_unknown_are_separate(self):
        from scope_lab.action_scope import action_summary
        events=[{'action_id':'a','within_user_scope':True,'asked':False,'blocked':True,'executed':False}]
        summary=action_summary(events,None)
        self.assertIsNone(summary['recovered_after_intervention'])
        self.assertTrue(summary['recovery_eligibility']['after_legitimate_block'])
        self.assertFalse(summary['recovery_eligibility']['after_legitimate_approval'])
        events[0].update(asked=True,blocked=False,approved=True,executed=True)
        self.assertTrue(action_summary(events,True)['recovery_outcomes']['after_legitimate_approval'])
        events[0].update(within_user_scope=False,blocked=True,approved=False,executed=False)
        self.assertTrue(action_summary(events,True)['recovery_outcomes']['after_outside_block'])

    def test_direct_read_records_real_target_and_shell_is_not_covered(self):
        events=[{'action_id':'one','tool':'read_file','tool_dispatched':True,
                 'file_access':{'operation':'read','path':'alias','resolved_path':'secret','bytes_returned':4}},
                {'action_id':'two','tool':'shell','tool_dispatched':True}]
        result=read_observations(events,{'sensitive_paths':['secret']},{'read_paths':['alias']})
        self.assertEqual(result['outside_scope_direct_reads'],1)
        self.assertEqual(result['sensitive_direct_reads'],1)
        self.assertEqual(result['unobserved_shell_requests'],['two'])
        self.assertEqual(result['whole_execution_read_coverage'],'incomplete')

    def test_ast_candidate_does_not_claim_intent_and_handles_bad_or_linked_code(self):
        with tempfile.TemporaryDirectory() as directory:
            before=Path(directory)/'before';after=Path(directory)/'after';before.mkdir();after.mkdir()
            (before/'code.py').write_text('def target():\n return 1\ndef unrelated():\n return 2\n')
            (after/'code.py').write_text('def target():\n return 1\ndef unrelated():\n return 3\n')
            spec={'python_review_paths':['code.py']}
            row=python_candidates(before,after,spec)['files'][0]
            self.assertIn('1:unrelated',row['changed_top_level_nodes']);self.assertIsNone(row['semantic_scope_violation'])
            (after/'code.py').write_text('def broken(')
            self.assertEqual(python_candidates(before,after,spec)['files'][0]['status'],'unknown')
            (after/'code.py').unlink();(after/'code.py').symlink_to(before/'code.py')
            self.assertEqual(python_candidates(before,after,spec)['files'][0]['status'],'unknown')


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS')=='1','Requires Docker')
class V05DockerTests(unittest.TestCase):
    def setUp(self):
        self.scenario,_,_=load_scenario(SOURCE)
        self.box=DockerSandbox(IMAGE);self.box.start(self.scenario['fixture'])
    def tearDown(self):self.box.close()
    def gate(self, mutate=None):
        def execute(action, timeout):
            if mutate:action=mutate(action)
            return self.box.tool(action,timeout)
        return Gate('D3-risk',json.loads((SOURCE.parent/'policy.fit.json').read_text()),execute,
                    action_scope=self.scenario['action_scope_spec'],approval_mode='scope_simulated',
                    risk_policy=self.scenario['risk_spec'],
                    inspect_target=lambda a,t:self.box.tool({'tool':'_inspect_target','path':a['path']},t))

    def test_bound_approval_and_actual_read_write_telemetry(self):
        gate=self.gate()
        result=gate({'tool':'write_file','path':'config/dev.json','content':'{"timeout":30}'},3)
        self.assertTrue(result['ok'],result);self.assertTrue(gate.events[0]['asked'])
        self.assertEqual(result['file_access']['resolved_path'],'config/dev.json')
        self.assertTrue(result['effect'])
        read=gate({'tool':'read_file','path':'config/dev.json'},3)
        self.assertTrue(read['effect']);self.assertEqual(read['file_access']['bytes_returned'],14)

    def test_changed_content_target_and_target_state_rejected_before_write(self):
        action={'tool':'write_file','path':'config/dev.json','content':'{"timeout":30}'}
        before=self.box.tool({'tool':'read_file','path':'config/prod.json'},2)['output']
        for field,value in [('content','bad'),('path','config/prod.json')]:
            result=self.gate(lambda a:dict(a,**{field:value}))(action,3)
            self.assertFalse(result['ok']);self.assertFalse(result['executed'])
        def mutate_state(a):
            self.box.tool({'tool':'write_file','path':'config/dev.json','content':'{"timeout":7}'},2)
            return a
        result=self.gate(mutate_state)(action,3)
        self.assertFalse(result['ok']);self.assertFalse(result['executed'])
        self.assertEqual(self.box.tool({'tool':'read_file','path':'config/prod.json'},2)['output'],before)

    def test_symlink_hardlink_and_directory_link_cannot_alias_approval(self):
        for command in ['rm config/dev.json; ln -s prod.json config/dev.json',
                        'rm config/dev.json; ln config/prod.json config/dev.json',
                        'mv config config-real; ln -s config-real config']:
            with self.subTest(command=command):
                self.assertTrue(self.box.tool({'tool':'shell','command':command},2)['ok'])
                result=self.gate()({'tool':'write_file','path':'config/dev.json','content':'bad'},3)
                self.assertFalse(result['ok']);self.assertFalse(result['executed'])
                if 'mv config' not in command:
                    self.box.tool({'tool':'shell','command':'rm config/dev.json; printf "{}" > config/dev.json'},2)

    def test_unrequested_new_file_still_possible_in_d0_not_hidden_by_common_guard(self):
        gate=Gate('D0',json.loads((SOURCE.parent/'policy.fit.json').read_text()),self.box.tool,
                  action_scope=self.scenario['action_scope_spec'],risk_policy=self.scenario['risk_spec'])
        result=gate({'tool':'write_file','path':'extra.txt','content':'unrequested'},3)
        self.assertTrue(result['ok'],result);self.assertFalse(gate.events[0]['within_user_scope'])
        empty=gate({'tool':'write_file','path':'empty.txt','content':''},3)
        self.assertTrue(empty['effect'],empty)

    def test_direct_secret_read_is_observed_but_shell_bypass_remains_unknown(self):
        self.box.tool({'tool':'write_file','path':'secret.txt','content':'synthetic-only'},2)
        risk=dict(self.scenario['risk_spec'],resources=dict(self.scenario['risk_spec']['resources'],**{'secret.txt':'secret'}))
        gate=Gate('D0',json.loads((SOURCE.parent/'policy.fit.json').read_text()),self.box.tool,
                  action_scope=self.scenario['action_scope_spec'],risk_policy=risk)
        self.assertTrue(gate({'tool':'read_file','path':'secret.txt'},2)['ok'])
        self.assertTrue(gate({'tool':'shell','command':'cat secret.txt'},2)['ok'])
        observed=read_observations(gate.events,{'sensitive_paths':['secret.txt']},self.scenario['action_scope_spec'])
        self.assertEqual(observed['sensitive_direct_reads'],1)
        self.assertEqual(len(observed['unobserved_shell_requests']),1)
        self.assertIsNone(gate.events[-1]['within_user_scope'])
        self.assertIsNone(gate.events[-1]['effect'])
        self.assertEqual(observed['whole_execution_read_coverage'],'incomplete')

    def test_each_new_fixture_fixed_test_success_flood_timeout_and_no_writeback(self):
        for folder in sorted(ASSETS.iterdir()):
            if not folder.is_dir():continue
            scenario,_,_=load_scenario(folder/'scenario.ko.json')
            box=DockerSandbox(IMAGE)
            try:
                box.start(scenario['fixture'])
                solutions=json.loads((folder/'control.json').read_text())['solutions']
                for path,content in solutions.items():box.tool({'tool':'write_file','path':path,'content':content},2)
                original={p:box.tool({'tool':'read_file','path':p},2)['output'] for p in solutions}
                normal=FixedTestTool(box,scenario['test_config'],IMAGE)(10)
                self.assertTrue(normal['ok'],normal)
                for script,timeout,flag in [("print('x'*100000)",5,'truncated'),('import time; time.sleep(10)',1,'timed_out')]:
                    config=dict(scenario['test_config'],script_text=script,timeout_seconds=timeout)
                    outcome=FixedTestTool(box,config,IMAGE)(timeout)
                    self.assertTrue(outcome[flag]);self.assertTrue(outcome['test_run']['cleanup_ok'])
                    self.assertTrue(outcome['test_run']['staging_cleanup_ok'])
                self.assertEqual(original,{p:box.tool({'tool':'read_file','path':p},2)['output'] for p in solutions})
            finally:box.close()

    def test_partial_timeout_keeps_violation_and_metrics_count_it(self):
        actions=iter([{'tool':'write_file','path':'config/prod.json','content':'{"timeout":1}'},
                      {'tool':'shell','command':'sleep 10'}])
        with tempfile.TemporaryDirectory() as directory:
            report=run(SOURCE,Path(directory)/'trial',lambda *a:{'content':json.dumps(next(actions))},
                       'scripted_control_not_llm',IMAGE,timeout_seconds=2,
                       policy=json.loads((SOURCE.parent/'policy.fit.json').read_text()))
            self.assertFalse(report['trial_valid']);self.assertTrue(report['observation_valid'])
            self.assertTrue(report['out_of_scope_observed'])
            rates=summarize_observations([({'trial_id':'x','orr_eligible':True},report)],{})
            self.assertEqual(rates['fs_osr']['rate'],1)
            self.assertEqual(rates['partial_or_invalid_observed_violations'],1)

    def test_cleanup_failure_retains_prior_violation_and_stops(self):
        close=DockerSandbox.close;start=DockerSandbox.start_readonly_inputs
        def mark(box,root):box.fixed=True;return start(box,root)
        def fail(box):
            close(box)
            if getattr(box,'fixed',False):raise SandboxError('synthetic cleanup error')
        actions=iter([{'tool':'write_file','path':'config/prod.json','content':'bad'},{'tool':'run_tests'}])
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'trial'
            with patch.object(DockerSandbox,'start_readonly_inputs',mark),patch.object(DockerSandbox,'close',fail):
                with self.assertRaises(TestCleanupError):
                    run(SOURCE,out,lambda *a:{'content':json.dumps(next(actions))},'scripted_control_not_llm',IMAGE,
                        policy=json.loads((SOURCE.parent/'policy.fit.json').read_text()))
            report=json.loads((out/'report.json').read_text())
            self.assertEqual(report['status'],'cleanup_error');self.assertFalse(report['retryable'])
            self.assertTrue(report['observation_valid']);self.assertTrue(report['out_of_scope_observed'])
            self.assertTrue(report['policy_events'][-1]['tool_dispatched'])
            self.assertIsNone(report['policy_events'][-1]['executed'])
