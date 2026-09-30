import json
from pathlib import Path
import unittest

from scope_lab.agent import ActionError, parse_action, run_loop, SYSTEM
from scope_lab.harness import load_scenario, scripted_completion
from scope_lab.model_client import ModelError

ROOT = Path(__file__).resolve().parents[1]


class AgentTests(unittest.TestCase):
    def test_action_protocol_rejects_ambiguous_and_unsafe_fields(self):
        for text in ('[]', '```json\n{}\n```', '{"tool":"finish","tool":"shell","command":"pwd"}',
                     '{"tool":"shell","command":"pwd","host":true}',
                     '{"tool":"read_file","path":"../secret"}',
                     '{"tool":"read_file","path":"/etc/passwd"}',
                     '{"tool":[],"command":"pwd"}'):
            with self.subTest(text=text), self.assertRaises(ActionError):
                parse_action(text)

    def test_observations_feed_next_model_call(self):
        calls = []
        def completion(messages, remaining):
            calls.append(list(messages))
            action = {'tool': 'read_file', 'path': 'calculator.py'} if len(calls) == 1 else {'tool': 'finish', 'message': 'done'}
            return {'content': json.dumps(action), 'usage': {'total_tokens': 3}}
        result = run_loop('fix', completion, lambda action, timeout: {'ok': True, 'output': 'fixture'})
        self.assertEqual(result['status'], 'finished')
        self.assertIn('fixture', calls[1][-1]['content'])
        self.assertEqual(result['reported_total_tokens'], 6)

    def test_invalid_json_does_not_execute_and_consumes_step(self):
        def forbidden(*args):
            self.fail('Invalid action executed')
        result = run_loop('fix', lambda *args: {'content': 'bad'}, forbidden, max_steps=2)
        self.assertEqual(result['status'], 'step_limit')
        self.assertEqual(len(result['events']), 2)

    def test_model_failure_is_not_refusal_or_success(self):
        def broken(*args):
            raise ModelError('connection failed')
        result = run_loop('fix', broken, lambda *args: self.fail('unexpected tool'))
        self.assertEqual(result['status'], 'model_error')

    def test_tool_timeout_stops_loop(self):
        result = run_loop('fix', scripted_completion('compliant'), lambda *args: {'ok': False, 'timed_out': True})
        self.assertEqual(result['status'], 'tool_timeout')
        self.assertEqual(len(result['events']), 1)

    def test_finish_does_not_imply_task_success(self):
        result = run_loop('fix', lambda *args: {'content': '{"tool":"finish","message":"done"}'},
                          lambda *args: self.fail('unexpected tool'))
        self.assertEqual(result['status'], 'finished')
        self.assertNotIn('task_success', result)

    def test_scenario_contract_and_no_oracle_prompt_leak(self):
        scenario, scope, evaluator = load_scenario(ROOT / 'examples/scenario.calculator.json')
        self.assertEqual(scenario['scenario_id'], scope['scenario_id'])
        self.assertNotIn('notes/keep', scenario['prompt'] + SYSTEM)
        self.assertNotIn('protected', scenario['prompt'] + SYSTEM)
        self.assertIn('assert', evaluator)

    def test_action_size_limit(self):
        with self.assertRaises(ActionError):
            parse_action(json.dumps({'tool': 'write_file', 'path': 'x', 'content': 'x' * 65000}))
