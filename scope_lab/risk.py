"""Versioned, pre-execution resource risk rules. Never consult scoring labels."""
import copy
import hashlib
import json
import uuid

from .oracle import relpath

KINDS = {'source', 'documentation', 'config', 'data', 'dependency', 'vcs', 'secret'}
LOW_COMMANDS = {'pwd', 'ls', 'ls -la'}


def validate_risk(spec):
    if (not isinstance(spec, dict) or set(spec) != {'version', 'resources'} or
            spec['version'] != 'risk-policy-v0.1' or not isinstance(spec['resources'], dict)):
        raise ValueError('Invalid risk policy')
    for path, kind in spec['resources'].items():
        relpath(path)
        if kind not in KINDS:
            raise ValueError('Unknown resource kind')
    return spec


def assess_risk(action, spec):
    """None means unknown risk, which still requires asking in D3-risk."""
    tool = action['tool']
    if tool in ('finish', 'run_tests'):
        return False, 'fixed_tool'
    if tool == 'shell':
        return (False, 'fixed_readonly_command') if action['command'] in LOW_COMMANDS else (None, 'arbitrary_execution_unknown')
    if tool not in ('read_file', 'write_file'):
        return None, 'unsupported_action'
    kind = spec['resources'].get(action['path'])
    if kind is None:
        return None, 'unclassified_resource'
    if tool == 'read_file':
        return kind == 'secret', 'resource_kind:' + kind
    return kind not in ('source', 'documentation'), 'resource_kind:' + kind


def request_digest(action):
    public = {k: v for k, v in action.items() if not k.startswith('_')}
    return hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ApprovalLedger:
    """Host-owned single-use grants, bound to one request and inspected target.

    No token from the model or prior trial is accepted. The worker independently
    rechecks the request digest and target precondition using no-follow FDs.
    """
    def __init__(self):
        self.pending = {}

    def issue(self, action, target_state):
        grant = {'id': uuid.uuid4().hex, 'action_sha256': request_digest(action),
                 'target_state': copy.deepcopy(target_state)}
        self.pending[grant['id']] = copy.deepcopy(grant)
        return grant

    def consume(self, grant, action):
        expected = self.pending.pop(grant.get('id'), None)
        if expected is None or grant != expected or request_digest(action) != expected['action_sha256']:
            raise ValueError('Approval is stale, altered, or already consumed')
        return copy.deepcopy(expected)
