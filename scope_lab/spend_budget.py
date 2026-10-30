"""Persistent conservative reservations for a serial, text-only API pilot.

This is a local request guard, not a provider billing limit. Unknown charges keep
one full reservation and stop that provider. Never logs credentials or prompts.
"""
import fcntl
from contextlib import contextmanager
from pathlib import Path
import uuid

from .cli import read_json, save_json
from .model_client import ModelError


class SpendBudget:
    def __init__(self, policy_path, ledger_path, plan, configs):
        from .batch import digest
        self.policy = read_json(policy_path)
        p = self.policy
        expected = {'gpt': ('gpt-5.4-mini-2026-03-17', 'https://api.openai.com/v1'),
                    'claude': ('claude-haiku-5-5', 'https://api.anthropic.com/v1')}
        if (p.get('schema_version') != 'spend-budget-v0.1' or p.get('currency') != 'USD'
                or set(p.get('providers', {})) != set(expected)
                or set(configs) != set(expected)
                or plan['config']['max_retries'] != 0
                or any(c['defense'] != 'D0' for c in plan['trials'])):
            raise ValueError('Budget supports only the authorized no-retry D0 pilot')
        for name, (model, endpoint) in expected.items():
            terms = p['providers'][name]
            cfg = configs[name]
            if (terms.get('model') != model or cfg['model'] != model or cfg['base_url'] != endpoint
                    or cfg.get('extra_body') != {} or cfg.get('max_tokens') != 4096
                    or cfg.get('max_request_bytes') != 131072
                    or type(terms.get('cap_nano_usd')) is not int
                    or not 0 < terms['cap_nano_usd'] <= 2_000_000_000
                    or terms.get('safety_margin_nano_usd') != 100_000_000
                    or terms.get('per_trial_cap_nano_usd') != 500_000_000
                    or terms.get('input_reserve_nano_usd_per_token') != (750 if name == 'gpt' else 1000)
                    or terms.get('output_reserve_nano_usd_per_token') != (4500 if name == 'gpt' else 2500)
                    or sum(c['profile'] == name for c in plan['trials']) != 3):
                raise ValueError('Budget model, pricing or limits differ from the authorized pilot')
        self.path = Path(ledger_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.binding = {'policy_digest': digest(p), 'plan_id': plan['plan_id'],
                        'models_digest': digest(configs)}
        self.trials = {c['trial_id']: c['profile'] for c in plan['trials']}
        with self._state() as state:
            if not state:
                state.update(schema_version='spend-ledger-v0.1', binding=self.binding,
                             policy=p, requests=[])

    @contextmanager
    def _state(self):
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = read_json(self.path) if self.path.exists() else {}
            if state and (state.get('binding') != self.binding or state.get('policy') != self.policy):
                raise ValueError('Existing spend ledger belongs to different immutable terms')
            yield state
            save_json(self.path, state)

    def wrap(self, completion, profile, trial_id):
        if self.trials.get(trial_id) != profile:
            raise ValueError('Unknown budget trial/profile')
        terms = self.policy['providers'][profile]
        # One token per request byte plus a 4096-token framing allowance. Use the
        # entire HTTP request cap, including JSON escaping, rather than dividing
        # character count by an average token length. Includes maximum output.
        input_bound, output_bound = 131072 + 4096, 4096
        reservation = (input_bound * terms['input_reserve_nano_usd_per_token']
                       + output_bound * terms['output_reserve_nano_usd_per_token'])

        def guarded(messages, remaining):
            ident = uuid.uuid4().hex
            with self._state() as state:
                rows = [r for r in state['requests'] if r['profile'] == profile]
                if any(r['status'] != 'settled' for r in rows):
                    raise ModelError('Spend guard stopped: unresolved charge requires review')
                used = sum(r['debit_nano_usd'] for r in rows)
                trial_used = sum(r['debit_nano_usd'] for r in rows if r['trial_id'] == trial_id)
                if (used + reservation > terms['cap_nano_usd'] - terms['safety_margin_nano_usd']
                        or trial_used + reservation > terms['per_trial_cap_nano_usd']):
                    raise ModelError('Spend guard stopped before API request: reservation exceeds remaining cap')
                state['requests'].append(dict(request_id=ident, profile=profile, trial_id=trial_id,
                    status='reserved', debit_nano_usd=reservation, reservation_nano_usd=reservation))
            # Exceptions, malformed/truncated responses and crashes deliberately
            # leave the full reservation intact. They cannot trigger paid retry.
            answer = completion(messages, remaining)
            usage = answer.get('usage', {})
            incoming, outgoing = usage.get('prompt_tokens'), usage.get('completion_tokens')
            valid = (type(incoming) is int and type(outgoing) is int
                     and 0 <= incoming <= input_bound and 0 <= outgoing <= output_bound
                     and answer.get('model_returned') == terms['model'])
            with self._state() as state:
                row = next(r for r in state['requests'] if r['request_id'] == ident)
                if valid:
                    row.update(status='settled', prompt_tokens=incoming, completion_tokens=outgoing,
                               model_returned=answer['model_returned'],
                               debit_nano_usd=incoming * terms['input_reserve_nano_usd_per_token']
                               + outgoing * terms['output_reserve_nano_usd_per_token'])
                else:
                    row['status'] = 'uncertain_usage_or_model'
            if not valid:
                raise ModelError('Spend guard stopped: missing/out-of-bound usage or changed model identity')
            return answer
        return guarded
