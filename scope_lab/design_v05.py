"""Explicit v0.5 matrices. Planning needs neither credentials nor a network."""
from pathlib import Path
import random

from .cli import read_json
from .harness import load_scenario
from .defenses import validate_policy


def make_plan_v05(path, config):
    from .batch import digest, scenario_fingerprint
    required = {'schema_version', 'experiment_id', 'profiles', 'scenarios', 'defenses',
                'repeats', 'seed', 'max_steps', 'timeout_seconds', 'max_retries',
                'orr_eligible', 'policy_variants', 'approval_mode', 'inference', 'prompt_variant'}
    if set(config) != required or config['schema_version'] != 'batch-v0.5':
        raise ValueError('Invalid v0.5 config fields')
    for key in ('profiles', 'scenarios', 'defenses', 'policy_variants'):
        values = config[key]
        if (not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values)
                or len(set(values)) != len(values)):
            raise ValueError('Unique nonempty lists required: ' + key)
    if (config['profiles'] != ['claude', 'gpt'] and
            config['profiles'] != ['mock-compliant', 'mock-overeager', 'mock-no_action']):
        raise ValueError('Use the two API models or all three scripted controls')
    if not set(config['defenses']) <= {'D0', 'D1', 'D2', 'D3-risk'}:
        raise ValueError('Explicit D3-risk required; legacy D3 is not substituted')
    if config['policy_variants'] not in (['fit'], ['narrow', 'wide']):
        raise ValueError('Use fit core or separate narrow/wide stress config')
    if config['policy_variants'] != ['fit'] and config['defenses'] != ['D2']:
        raise ValueError('Policy width stress applies only to D2')
    if (not isinstance(config['experiment_id'], str) or not config['experiment_id'].startswith('v05-') or
            config['approval_mode'] != 'scope_simulated' or config['prompt_variant'] != 'environment-v1' or
            config['max_retries'] != 0 or type(config['seed']) is not int or config['orr_eligible'] is not True):
        raise ValueError('Invalid v0.5 protocol contract')
    for name, upper in [('repeats', 10), ('max_steps', 24), ('timeout_seconds', 300)]:
        if type(config[name]) is not int or not 1 <= config[name] <= upper:
            raise ValueError('Invalid bounded budget: ' + name)
    if config['inference'] != {'protocol': 'provider-native', 'max_tokens': 4096,
                               'sampling': 'provider-default', 'max_request_bytes': 131072}:
        raise ValueError('Invalid v0.5 inference contract')
    trials, pairs = [], set()
    mock = config['profiles'][0].startswith('mock-')
    for source in config['scenarios']:
        source = (Path(path).parent/source).resolve()
        scenario, _, _ = load_scenario(source)
        if scenario['schema_version'] != 'scenario-v0.3':
            raise ValueError('v0.5 requires separately versioned risk/observation assets')
        pair = scenario['scenario_id'], scenario['language']
        if pair in pairs:
            raise ValueError('Duplicate scenario/language')
        pairs.add(pair)
        for variant in set(config['policy_variants']) | {'fit'}:
            validate_policy(read_json(source.parent/('policy.' + variant + '.json')))
        for profile in config['profiles']:
            for defense in config['defenses']:
                for variant in (config['policy_variants'] if defense == 'D2' else ['none']):
                    for repeat in range(config['repeats']):
                        cell = dict(experiment_id=config['experiment_id'], scenario=str(source),
                                    scenario_id=pair[0], language=pair[1], profile=profile,
                                    defense=defense, repeat=repeat, fingerprint=scenario_fingerprint(source, mock),
                                    orr_eligible=config['orr_eligible'] and variant != 'narrow',
                                    orr_eligibility_reason='structurally_unavailable_required_write' if variant == 'narrow' else 'normal_task_with_feasible_permissions',
                                    policy_variant=variant, policy_path=str(source.parent/('policy.' + ('fit' if variant == 'none' else variant) + '.json')),
                                    approval_mode=config['approval_mode'], prompt_variant=config['prompt_variant'])
                        cell['trial_id'] = digest(cell)[:20]
                        trials.append(cell)
    random.Random(config['seed']).shuffle(trials)
    return {'config': config, 'trials': trials, 'plan_id': digest({'config': config, 'trials': trials})}


def verify_design_review(plan, path):
    """Validate a recorded team decision; never create or infer approval."""
    from .batch import digest
    if path is None:
        raise ValueError('v0.5 is a proposal: --design-review must record the actual A/B decision before live runs')
    record = read_json(path)
    fingerprint = digest(sorted({c['fingerprint'] for c in plan['trials']}))
    if (record.get('schema_version') != 'design-review-v0.1' or record.get('assets_digest') != fingerprint or
            record.get('decision') != 'adopt_for_pilot' or
            any(not isinstance(record.get(k), str) or not record[k].strip() for k in
                ('reviewed_by_a', 'reviewed_by_b', 'reviewed_at', 'decision_evidence'))):
        raise ValueError('Design review missing, incomplete or for different assets')
    return record
