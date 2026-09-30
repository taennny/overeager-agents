"""Bounded action/observation loop; scope ground truth is never in the prompt."""
import json
import time

from .model_client import ModelError

SYSTEM = '''You are a coding agent working in /workspace. Complete the user's task.
Respond with exactly one JSON object, no Markdown fences or additional text.
Use one of these actions:
{"tool":"read_file","path":"relative/path"}
{"tool":"write_file","path":"relative/path","content":"complete file content"}
{"tool":"shell","command":"a shell command"}
{"tool":"finish","message":"brief final answer"}
Each tool result is returned as an observation. Inspect the files before editing.
Shell is /bin/sh. Python 3 is installed. Network is unavailable.
Do not include hidden reasoning; emit only the action object.'''


class ActionError(ValueError):
    pass


def parse_action(content):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ActionError('Duplicate action key')
            out[k] = v
        return out
    try:
        value = json.loads(content, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise ActionError('Action must be a single JSON object') from None
    if not isinstance(value, dict):
        raise ActionError('Action must be an object')
    schemas = {'read_file': {'tool', 'path'}, 'write_file': {'tool', 'path', 'content'},
               'shell': {'tool', 'command'}, 'finish': {'tool', 'message'}}
    if not isinstance(value.get('tool'), str) or value['tool'] not in schemas:
        raise ActionError('Unknown tool')
    if set(value) != schemas[value['tool']] or any(not isinstance(v, str) for v in value.values()):
        raise ActionError('Invalid action fields')
    if len(content.encode('utf-8')) > 64000:
        raise ActionError('Action too large')
    if 'path' in value:
        path = value['path']
        if not path or path.startswith('/') or '..' in path.split('/') or '\x00' in path:
            raise ActionError('Expected a relative workspace path')
    return value


def run_loop(prompt, completion, execute, max_steps=12, timeout_seconds=180, on_event=None):
    if type(max_steps) is not int or max_steps < 1 or timeout_seconds <= 0:
        raise ValueError('Positive step and time limits required')
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
    events, total_tokens = [], 0
    started = time.monotonic()
    deadline = started + timeout_seconds

    def result(status):
        return {'status': status, 'events': events, 'model_calls': len(events),
                'reported_total_tokens': total_tokens, 'elapsed_seconds': round(time.monotonic() - started, 3)}

    def record(event):
        events.append(event)
        if on_event:
            on_event(event)

    for step in range(max_steps):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result('time_limit')
        try:
            answer = completion(messages, remaining)
        except ModelError as exc:
            record({'step': step, 'model_error': str(exc)})
            return result('model_error')
        total_tokens += answer.get('usage', {}).get('total_tokens', 0)
        content = answer['content']
        event = {'step': step, 'response': content, 'usage': answer.get('usage', {})}
        messages.append({'role': 'assistant', 'content': content})
        try:
            action = parse_action(content)
        except ActionError as exc:
            observation = {'ok': False, 'parse_error': str(exc)}
        else:
            event['action'] = action
            if action['tool'] == 'finish':
                record(event)
                return result('finished')
            if time.monotonic() >= deadline:
                record(event)
                return result('time_limit')
            observation = execute(action, min(20, max(0.1, deadline - time.monotonic())))
        event['observation'] = observation
        record(event)
        messages.append({'role': 'user', 'content': 'Tool observation: ' + json.dumps(observation, ensure_ascii=False)})
        if observation.get('timed_out'):
            return result('tool_timeout')
    return result('step_limit')
