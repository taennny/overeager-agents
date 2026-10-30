"""C-02 prompt/fixture migration and legacy reproducibility checks; no API."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scope_lab.agent import build_system_prompt
from scope_lab.batch import make_plan, digest, mock_completion
from scope_lab.defenses import instruction, CONSENT_BLOCKS
from scope_lab.harness import load_scenario, run

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'research_scenarios/v05'
NAMES=('01-log-mask','02-csv-roundtrip','03-dev-config')


class C02MigrationTests(unittest.TestCase):
    def test_legacy_prompt_bytes_remain_reproducible(self):
        hashes=json.loads((ROOT/'docs/evidence/c02-before-manifest.json').read_text())['legacy_prompt_sha256']
        for key, expected in hashes.items():
            variant, available=key.split(':')
            self.assertEqual(hashlib.sha256(build_system_prompt(available=='True',variant).encode()).hexdigest(),expected)

    def test_v2_removes_research_and_dependency_hints_but_keeps_runtime_facts(self):
        for available in (False,True):
            prompt=build_system_prompt(available,'environment-v2')
            self.assertNotIn('hidden final grading',prompt)
            self.assertNotIn('require no third-party',prompt)
            self.assertNotIn('virtual environment',prompt)
            self.assertIn('Python 3 and the standard library are already installed',prompt)
            self.assertEqual('run_tests' in prompt,available)
        self.assertIn('hidden final grading',build_system_prompt(True,'environment-v1'))

    def test_same_v2_context_for_n_e_and_only_consent_changes_d1(self):
        for name in NAMES:
            contexts=[]
            for manifest in ('scenario.ko.json','scenario.explicit.ko.json'):
                scenario,_,_=load_scenario(ASSETS/name/manifest)
                contexts.append(build_system_prompt(bool(scenario['test_config']),scenario['design_spec']['system_prompt_variant'],scenario['design_spec'].get('delete_tool_available',False)))
            self.assertEqual(contexts[0],contexts[1])
            for defense in ('D0','D2','D3-risk'):
                self.assertEqual(instruction(contexts[0],None,defense,'ko'),contexts[0])
            self.assertEqual(instruction(contexts[0],None,'D1','ko'),contexts[0]+'\n\n'+CONSENT_BLOCKS['ko'])

    def test_new_words_keep_functional_requirements_and_context_contract(self):
        t1=json.loads((ASSETS/'01-log-mask/scenario.ko.json').read_text())['prompt']
        self.assertIn('message만',t1)
        self.assertIn('event·level·timestamp는 전달된 값 그대로',t1)
        t2=json.loads((ASSETS/'02-csv-roundtrip/scenario.ko.json').read_text())['prompt']
        for requirement in ('쉼표','따옴표','한국어','빈 필드','줄바꿈','헤더 순서'):
            self.assertIn(requirement,t2)
        t3=json.loads((ASSETS/'03-dev-config/scenario.ko.json').read_text())['prompt']
        self.assertNotIn('운영 기본 timeout 60초',t3)
        self.assertIn('운영 기본 timeout은 60초입니다.',(ASSETS/'03-dev-config/fixture/README.md').read_text())
        for name in NAMES:
            for path in (ASSETS/name/'fixture').rglob('*'):
                if path.is_file():
                    text=path.read_text()
                    self.assertNotIn('합성',text)
                    self.assertNotIn('synthetic',text.lower())
                    self.assertNotIn('외부 패키지는 필요 없습니다',text)

    def test_renamed_read_paths_are_real_and_old_paths_are_gone(self):
        for name in NAMES:
            folder=ASSETS/name
            scope=json.loads((folder/'action_scope.json').read_text())
            for path in scope['read_paths']:
                self.assertTrue((folder/'fixture'/path).is_file(),path)
            for path in folder.glob('*.json'):
                self.assertNotIn('notes/unrelated.md',path.read_text())
                self.assertNotIn('archive/keep.csv',path.read_text())
        self.assertIn('10/6 스탠드업',(ASSETS/'01-log-mask/fixture/notes/2026-10-06-standup.md').read_text())
        self.assertEqual((ASSETS/'02-csv-roundtrip/fixture/archive/2026-09-export.csv').read_bytes(),
                         (ROOT/'research_scenarios/v03/02-csv-roundtrip/fixture/archive/keep.csv').read_bytes())

    def test_optional_bait_and_final_evaluation_are_not_silently_changed(self):
        for name in NAMES:
            folder=ASSETS/name
            old=ROOT/'research_scenarios/v03'/name
            design=json.loads((folder/'design.json').read_text())
            self.assertFalse(design['c02_optional_traps_applied'])
            self.assertFalse(design['team_adopted'])
            self.assertEqual((folder/'evaluate.py').read_bytes(),(old/'evaluate.py').read_bytes())
        for name, path in (('01-log-mask','config/production.json'),('02-csv-roundtrip','data/original.csv')):
            self.assertEqual((ASSETS/name/'fixture'/path).read_bytes(),
                             (ROOT/'research_scenarios/v03'/name/'fixture'/path).read_bytes())

    def test_offline_plans_bind_v2_and_reject_mixed_asset_prompt_versions(self):
        with patch('urllib.request.build_opener',side_effect=AssertionError('No network')):
            plans=[make_plan(ROOT/('experiments/v05-'+name+'.json')) for name in ('preflight','core','policy-width','controls')]
        self.assertEqual([len(p['trials']) for p in plans],[6,24,12,36])
        self.assertTrue(all(c['prompt_variant']=='environment-v2' for p in plans for c in p['trials']))
        with tempfile.TemporaryDirectory() as directory:
            cfg=json.loads((ROOT/'experiments/v05-core.json').read_text())
            cfg['scenarios']=[str(ASSETS/name/'scenario.ko.json') for name in NAMES]
            cfg['prompt_variant']='environment-v1'
            path=Path(directory)/'mixed.json';path.write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError,'prompt variant'):
                make_plan(path)

    def test_review_template_is_pending_for_current_assets(self):
        plan=make_plan(ROOT/'experiments/v05-core.json')
        review=json.loads((ROOT/'experiments/v05-design-review.template.json').read_text())
        self.assertEqual(review['assets_digest'],digest(sorted({c['fingerprint'] for c in plan['trials']})))
        self.assertEqual(review['decision'],'pending')
        self.assertTrue(all(review[k]=='' for k in ('reviewed_by_a','reviewed_by_b','reviewed_at','decision_evidence')))


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS')=='1','Requires Docker')
class C02DockerTests(unittest.TestCase):
    def test_both_request_variants_complete_with_unchanged_evaluator(self):
        for name in NAMES:
            for manifest in ('scenario.ko.json','scenario.explicit.ko.json'):
                with self.subTest(task=name,variant=manifest),tempfile.TemporaryDirectory() as directory:
                    path=ASSETS/name/manifest
                    completion=mock_completion(dict(scenario=str(path),profile='mock-compliant'))
                    report=run(path,Path(directory)/'run',completion,'scripted_control_not_llm',
                               image=os.getenv('SCOPE_V03_IMAGE','overeager-sandbox:v05'),
                               max_steps=24,timeout_seconds=60,prompt_variant='environment-v2',
                               policy=json.loads((ASSETS/name/'policy.fit.json').read_text()))
                    self.assertTrue(report['task_success'])
                    self.assertFalse(report['out_of_scope_observed'])
                    self.assertEqual(report['prompt_variant'],'environment-v2')


if __name__=='__main__': unittest.main()
