"""Persistent conservative reservations for a serial, text-only API pilot.

This is a local request guard, not a provider billing limit. Unknown charges keep
one full reservation and stop that provider. Never logs credentials or prompts.
"""
import fcntl
import hashlib
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
        expanded = p.get('schema_version') in ('spend-budget-v0.2', 'spend-budget-v0.3')
        if (p.get('schema_version') not in ('spend-budget-v0.1', 'spend-budget-v0.2', 'spend-budget-v0.3') or p.get('currency') != 'USD'
                or set(p.get('providers', {})) != set(expected)
                or set(configs) != set(expected)
                or plan['config']['max_retries'] != 0
                or (not expanded and any(c['defense'] != 'D0' for c in plan['trials']))):
            raise ValueError('Budget supports only the authorized no-retry D0 pilot')
        self.carryover = {name: 0 for name in expected}
        authorized = None
        if expanded:
            from .batch import make_plan
            root = Path(__file__).resolve().parents[1]
            phases = [make_plan(root/('experiments/v05-'+phase+'.json')) for phase in ('preflight', 'core')]
            authorized = {phase['config']['experiment_id']: phase['plan_id'] for phase in phases}
            if p.get('authorized_plan_ids') != authorized or plan not in phases:
                raise ValueError('Spend policy authorizes only the exact preflight/core matrices')
            carry = p.get('carryover', {})
            source = (Path(policy_path).resolve().parent/carry.get('ledger_path', '')).resolve()
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != carry.get('ledger_sha256'):
                raise ValueError('Previous spend ledger hash changed')
            previous = read_json(source)
            requests = previous.get('requests')
            if (previous.get('schema_version') not in ('spend-ledger-v0.1', 'spend-ledger-v0.2', 'spend-ledger-v0.3') or not isinstance(requests, list)
                    or any(r.get('profile') not in expected
                           or type(r.get('debit_nano_usd')) is not int or r['debit_nano_usd'] < 0 for r in requests)):
                raise ValueError('Previous spend ledger has unresolved or malformed charges')
            unresolved = [r for r in requests if r.get('status') != 'settled']
            reviews = carry.get('reviewed_uncertain_requests', {})
            if set(reviews) != {r.get('request_id') for r in unresolved}:
                raise ValueError('Previous spend ledger has unresolved or unreviewed charges')
            for row in unresolved:
                evidence = reviews[row['request_id']]
                report_path = (Path(policy_path).resolve().parent/evidence['report_path']).resolve()
                report_raw = report_path.read_bytes()
                report = read_json(report_path)
                profile = row['profile']
                reserve = (135168 * (750 if profile == 'gpt' else 1000)
                           + 4096 * (4500 if profile == 'gpt' else 2500))
                errors = [e.get('model_error', '') for e in report.get('agent', {}).get('events', [])]
                if (p['schema_version'] != 'spend-budget-v0.3' or row.get('status') != 'reserved'
                        or row.get('debit_nano_usd') != reserve or row.get('reservation_nano_usd') != reserve
                        or evidence.get('retain_nano_usd') != reserve
                        or evidence.get('disposition') != 'retain_uncertain_full_reservation'
                        or hashlib.sha256(report_raw).hexdigest() != evidence.get('report_sha256')
                        or report.get('status') != 'model_error' or report.get('cell', {}).get('trial_id') != row.get('trial_id')
                        or not any(e.startswith('No textual completion') for e in errors)
                        or not carry.get('operator_review_evidence')):
                    raise ValueError('Uncertain charge lacks a valid full-reservation operator review')
            floor = previous.get('carried_forward_debit_nano_usd', {name: 0 for name in expected})
            if (set(floor) != set(expected) or any(type(v) is not int or v < 0 for v in floor.values())):
                raise ValueError('Invalid previous carryover floor')
            self.carryover = {name: floor[name] + sum(r['debit_nano_usd'] for r in requests if r['profile'] == name)
                              for name in expected}
            if self.carryover != carry.get('debit_nano_usd'):
                raise ValueError('Previous spend totals do not match the frozen carryover')
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
                    or sum(c['profile'] == name for c in plan['trials']) != (12 if expanded and plan['config']['experiment_id'] == 'v05-c04-core' else 3)):
                raise ValueError('Budget model, pricing or limits differ from the authorized pilot')
        self.path = Path(ledger_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.binding = {'policy_digest': digest(p), 'plan_id': plan['plan_id'],
                        'models_digest': digest(configs)}
        if expanded:
            self.binding.pop('plan_id')
            self.binding.update(authorized_plans_digest=digest(authorized), carryover_digest=digest(p['carryover']))
        self.trials = {c['trial_id']: c['profile'] for c in plan['trials']}
        with self._state() as state:
            if not state:
                state.update(schema_version=('spend-ledger-v0.3' if p['schema_version'] == 'spend-budget-v0.3' else 'spend-ledger-v0.2') if expanded else 'spend-ledger-v0.1', binding=self.binding,
                             policy=p, requests=[])
                if expanded:
                    state['carried_forward_debit_nano_usd'] = self.carryover

    @contextmanager
    def _state(self):
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = read_json(self.path) if self.path.exists() else {}
            if state and (state.get('binding') != self.binding or state.get('policy') != self.policy or
                          (self.policy['schema_version'] in ('spend-budget-v0.2', 'spend-budget-v0.3') and
                           state.get('carried_forward_debit_nano_usd') != self.carryover)):
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
                used = self.carryover[profile] + sum(r['debit_nano_usd'] for r in rows)
                trial_used = sum(r['debit_nano_usd'] for r in rows if r['trial_id'] == trial_id)
                if (used + reservation > terms['cap_nano_usd'] - terms['safety_margin_nano_usd']
                        or trial_used + reservation > terms['per_trial_cap_nano_usd']):
                    raise ModelError('Spend guard stopped before API request: reservation exceeds remaining cap')
                state['requests'].append(dict(request_id=ident, profile=profile, trial_id=trial_id,
                    status='reserved', debit_nano_usd=reservation, reservation_nano_usd=reservation))
            # A provider response can carry billable usage without usable text.
            # Keep it a failed trial; only its bounded usage is settled. Unknown
            # charges and crashes still retain the full reservation and block.
            response_error = None
            try:
                answer = completion(messages, remaining)
            except ModelError as exc:
                if not isinstance(exc.diagnostics, dict):
                    raise
                response_error = exc
                answer = exc.diagnostics
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
            if response_error is not None:
                with self._state() as state:
                    row = next(r for r in state['requests'] if r['request_id'] == ident)
                    row['response_outcome'] = 'model_error_with_known_usage'
                raise response_error
            return answer
        return guarded
