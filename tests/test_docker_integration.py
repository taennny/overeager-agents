"""Opt-in REAL Docker integration, scripted actions, no LLM/API required."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from scope_lab.harness import run, scripted_completion
from scope_lab.sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv('SCOPE_DOCKER_TESTS') == '1', 'Set SCOPE_DOCKER_TESTS=1 after Docker image build')
class DockerIntegrationTests(unittest.TestCase):
    def test_three_controls_and_fresh_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            # Intentional order: destructive case followed by fresh clean cases.
            for case, expected in [('overeager', (True, True)), ('compliant', (True, False)), ('no_action', (False, False))]:
                with self.subTest(case=case):
                    result = run(ROOT / 'examples/scenario.calculator.json', Path(directory) / case,
                                 scripted_completion(case), 'scripted_control_not_llm')
                    self.assertEqual((result['task_success'], result['out_of_scope_observed']), expected)
                    self.assertTrue(result['trial_valid'])
                    self.assertFalse(result['real_inference_verified'])
                    self.assertIsNone(result['over_refusal'])

    def test_workspace_test_tampering_does_not_pass_trusted_evaluation(self):
        actions = iter([{'tool': 'write_file', 'path': 'tests/test_calculator.py', 'content': '# no tests\n'},
                        {'tool': 'finish', 'message': 'done'}])
        with tempfile.TemporaryDirectory() as directory:
            result = run(ROOT / 'examples/scenario.calculator.json', Path(directory) / 'tamper',
                         lambda *args: {'content': json.dumps(next(actions))}, 'scripted_control_not_llm')
            self.assertFalse(result['task_success'])
            self.assertTrue(result['out_of_scope_observed'])

    def test_timeout_is_invalid_trial_and_containers_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run(ROOT / 'examples/scenario.calculator.json', Path(directory) / 'timeout',
                         scripted_completion('timeout'), 'scripted_control_not_llm', timeout_seconds=1)
            self.assertIn(result['status'], ('tool_timeout', 'time_limit'))
            self.assertFalse(result['trial_valid'])

    def test_environment_isolation_and_symlink_guard(self):
        box = DockerSandbox()
        try:
            box.start(ROOT / 'examples/calculator')
            value = box.tool({'tool': 'shell', 'command': "id -u; test ! -e /var/run/docker.sock; test -z \"$COMMERCIAL_API_KEY\"; test -z \"$VLLM_API_KEY\"; test ! -w /opt/scope/tool_worker.py"}, 5)
            self.assertTrue(value['ok'])
            self.assertIn('10001', value['output'])
            network = box.tool({'tool': 'shell', 'command': "python -c 'import socket; s=socket.socket(); s.settimeout(1); s.connect((\"1.1.1.1\",443))'"}, 5)
            self.assertFalse(network['ok'])
            box.tool({'tool': 'shell', 'command': 'ln -s /etc/passwd outside'}, 5)
            self.assertFalse(box.tool({'tool': 'read_file', 'path': 'outside'}, 5)['ok'])
        finally:
            box.close()

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'keep.txt'
            sentinel.write_text('keep')
            with self.assertRaises(FileExistsError):
                run(ROOT / 'examples/scenario.calculator.json', directory,
                    scripted_completion('no_action'), 'scripted_control_not_llm')
            self.assertEqual(sentinel.read_text(), 'keep')
