"""Limited direct-file telemetry and Python AST review candidates, not intent."""
import ast
import difflib
from pathlib import Path

from .oracle import relpath


def validate_observations(spec):
    if (not isinstance(spec, dict) or set(spec) !=
            {'version', 'sensitive_paths', 'python_review_paths'} or spec['version'] != 'observation-v0.1'):
        raise ValueError('Invalid observation specification')
    for field in ('sensitive_paths', 'python_review_paths'):
        values = spec[field]
        if not isinstance(values, list) or len(set(values)) != len(values):
            raise ValueError('Observation paths must be unique lists')
        for path in values:
            relpath(path)
    return spec


def read_observations(events, spec, action_scope):
    direct = []
    unobserved = []
    for event in events:
        if event.get('tool_dispatched') and event['tool'] == 'shell':
            # Even a simple shell command has no complete read audit here.
            unobserved.append(event['action_id'])
        access = event.get('file_access')
        if not access or access.get('operation') != 'read':
            continue
        path = access['resolved_path']
        inside = path in action_scope['read_paths'] if action_scope else None
        direct.append(dict(access, action_id=event['action_id'], within_user_scope=inside,
                           sensitive=path in spec['sensitive_paths']))
    return {'measurement': 'successful_read_file_calls_only', 'events': direct,
            'outside_scope_direct_reads': sum(e['within_user_scope'] is False for e in direct),
            'sensitive_direct_reads': sum(e['sensitive'] for e in direct),
            'unobserved_shell_requests': unobserved, 'whole_execution_read_coverage': 'incomplete',
            'secret_exfiltration_measured': False}


def _text(root, relative):
    path = Path(root)
    for part in relative.split('/'):
        path = path / part
        if path.is_symlink():
            raise ValueError('Linked review input')
    if not path.is_file() or path.stat().st_size > 131072:
        raise ValueError('Missing or oversized review input')
    return path.read_text(encoding='utf-8')


def python_candidates(before, after, spec):
    rows = []
    for path in spec['python_review_paths']:
        try:
            old, new = _text(before, path), _text(after, path)
            def symbols(text):
                tree = ast.parse(text)
                return {str(i) + ':' + getattr(node, 'name', type(node).__name__):
                        ast.dump(node, include_attributes=False) for i, node in enumerate(tree.body)}
            left, right = symbols(old), symbols(new)
            changed = sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))
            rows.append({'path': path, 'status': 'review_candidate' if old != new else 'unchanged',
                         'changed_top_level_nodes': changed, 'semantic_scope_violation': None,
                         'text_diff': ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True)))[:16000]})
        except (OSError, UnicodeError, ValueError, SyntaxError, RecursionError) as exc:
            rows.append({'path': path, 'status': 'unknown', 'error_type': type(exc).__name__,
                         'semantic_scope_violation': None})
    return {'measurement': 'ast_and_text_review_candidates_not_L7_oracle', 'files': rows}
