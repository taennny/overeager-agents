"""Runs only INSIDE the disposable container. Never execute model code on host."""
import json
import base64
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import tempfile
import hashlib
from contextlib import contextmanager

LIMIT = 16000


class ApprovalBindingError(ValueError):
    pass


def collect_test_files(paths):
    """FD-relative reads reject links, hard links, special files and races."""
    if not isinstance(paths, list) or not paths or len(paths) > 64:
        raise ValueError('Invalid collection')
    files, total = {}, 0
    root = os.open('/workspace', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in paths:
            if (not isinstance(name, str) or name.startswith('/') or
                    any(p in ('', '.', '..') for p in name.split('/'))):
                raise ValueError('Invalid test input path')
            current = os.dup(root)
            try:
                parts = name.split('/')
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                    os.close(current)
                    current = child
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 131072:
                        raise ValueError('Unsupported test input')
                    with os.fdopen(fd, 'rb', closefd=False) as stream:
                        data = stream.read(131073)
                    after = os.fstat(fd)
                    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
                    if signature(before) != signature(after) or len(data) > 131072:
                        raise ValueError('Unstable or oversized test input')
                    total += len(data)
                    if total > 1048576:
                        raise ValueError('Test input budget exceeded')
                    files[name] = base64.b64encode(data).decode('ascii')
                finally:
                    os.close(fd)
            finally:
                os.close(current)
    finally:
        os.close(root)
    return {'ok': True, 'files': files}


def local_path(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Expected a relative workspace path")
    resolved = (Path('/workspace') / path).resolve()
    if resolved != Path('/workspace') and Path('/workspace') not in resolved.parents:
        raise ValueError("File tool cannot follow links outside workspace")
    return resolved


@contextmanager
def target_fd(name, writing=False, create=False):
    """Anchor every path component; never follow links in a guarded request."""
    if (not isinstance(name, str) or name.startswith('/') or
            any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('Noncanonical target')
    parent = os.open('/workspace', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    parents = []
    created = False
    try:
        for part in name.split('/')[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
            st = os.fstat(parent)
            parents.append([st.st_dev, st.st_ino])
        leaf = name.split('/')[-1]
        flags = (os.O_RDWR if writing else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            fd = os.open(leaf, flags, dir_fd=parent)
        except FileNotFoundError:
            if not (writing and create):
                raise
            fd = os.open(leaf, flags | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=parent)
            created = True
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError('Target must be a single-link regular file')
        yield fd, parents, created
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def target_state(fd, parents):
    before = os.fstat(fd)
    if before.st_size > 131072:
        raise ValueError('Target binding exceeds size budget')
    data = os.pread(fd, 131073, 0)
    after = os.fstat(fd)
    signature = lambda s: [s.st_dev, s.st_ino, s.st_mode, s.st_nlink,
                           s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    if signature(before) != signature(after) or len(data) > 131072:
        raise ValueError('Unstable target')
    return {'stat': signature(after), 'parents': parents,
            'sha256': hashlib.sha256(data).hexdigest()}


def check_binding(action):
    grant = action.get('_approval_binding')
    if grant is not None:
        keys = {'read_file': ('tool', 'path'), 'write_file': ('tool', 'path', 'content'),
                'shell': ('tool', 'command'), 'run_tests': ('tool',)}
        request = {k: action[k] for k in keys[action['tool']]}
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if grant.get('action_sha256') != digest:
            raise ApprovalBindingError('approved_request_changed')


def main():
    action = json.loads(sys.stdin.read(70000))
    tool = action['tool']
    executed = False
    try:
        check_binding(action)
        if '_permitted_targets' in action:
            target = local_path(action['path']).relative_to('/workspace').as_posix()
            if target not in action['_permitted_targets']:
                raise ValueError('Resolved target outside policy')
        if tool == '_collect_test_files':
            result = collect_test_files(action['paths'])
        elif tool == '_inspect_target':
            with target_fd(action['path']) as (fd, parents, created):
                result = {'ok': True, 'target_state': target_state(fd, parents)}
        elif tool in ('read_file', 'write_file') and any(k in action for k in ('_permitted_targets', '_approval_binding', '_no_follow')):
            # No truncation or read occurs until the approved object is verified.
            with target_fd(action['path'], writing=tool == 'write_file',
                           create=bool(action.get('_no_follow')) and '_approval_binding' not in action and '_permitted_targets' not in action) as (fd, parents, created):
                state = target_state(fd, parents)
                grant = action.get('_approval_binding')
                if grant and grant.get('target_state') is not None and grant['target_state'] != state:
                    raise ApprovalBindingError('approved_target_changed')
                if tool == 'read_file':
                    data = os.pread(fd, LIMIT + 1, 0)
                    executed = True
                    result = {'ok': True, 'output': data[:LIMIT].decode('utf-8', errors='replace'),
                              'truncated': len(data) > LIMIT, 'effect': True,
                              'effect_observation': 'direct_file_read',
                              'file_access': {'operation': 'read', 'path': action['path'],
                                              'resolved_path': action['path'], 'bytes_returned': min(len(data), LIMIT)}}
                else:
                    data = action['content'].encode('utf-8')
                    executed = True
                    os.ftruncate(fd, 0)
                    with os.fdopen(fd, 'wb', closefd=False) as stream:
                        stream.write(data)
                        stream.flush()
                    result = {'ok': True, 'output': 'written',
                              'effect': created or state['sha256'] != hashlib.sha256(data).hexdigest(),
                              'effect_observation': 'direct_file_content_change',
                              'file_access': {'operation': 'write', 'path': action['path'],
                                              'resolved_path': action['path'], 'bytes_written': len(data)}}
        elif tool == 'read_file':
            path = local_path(action['path'])
            executed = True
            with path.open('rb') as stream:
                data = stream.read(LIMIT + 1)
            result = {'ok': True, 'output': data[:LIMIT].decode('utf-8', errors='replace'),
                      'truncated': len(data) > LIMIT, 'effect': True,
                      'effect_observation': 'direct_file_read',
                      'file_access': {'operation': 'read', 'path': action['path'],
                                      'resolved_path': path.relative_to('/workspace').as_posix(),
                                      'bytes_returned': min(len(data), LIMIT)}}
        elif tool == 'write_file':
            path = local_path(action['path'])
            before = path.read_bytes() if path.is_file() and path.stat().st_size <= 131072 else None
            executed = True
            path.write_text(action['content'], encoding='utf-8')
            result = {'ok': True, 'output': 'written', 'effect': before != action['content'].encode('utf-8'),
                      'effect_observation': 'direct_file_content_change',
                      'file_access': {'operation': 'write', 'path': action['path'],
                                      'resolved_path': path.relative_to('/workspace').as_posix(),
                                      'bytes_written': len(action['content'].encode('utf-8'))}}
        elif tool == 'shell':
            # Bound individual files and captured output; process count/memory also
            # limited by Docker. Container kill handles background descendants.
            def limits():
                resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024,) * 2)
            with tempfile.TemporaryFile() as output:
                proc = subprocess.Popen(['/bin/sh', '-c', action['command']],
                                        stdout=output, stderr=subprocess.STDOUT,
                                        start_new_session=True, preexec_fn=limits)
                executed = True
                timed_out = False
                try:
                    proc.wait(timeout=action['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    timed_out = True
                finally:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                output.seek(0)
                data = output.read(LIMIT + 1)
            result = {'ok': proc.returncode == 0 and not timed_out, 'returncode': proc.returncode,
                      'timed_out': timed_out, 'output': data[:LIMIT].decode('utf-8', errors='replace'),
                      'truncated': len(data) > LIMIT}
        else:
            raise ValueError('Unknown tool')
    except (OSError, ValueError) as exc:
        result = {'ok': False, 'error': type(exc).__name__}
        if not executed:
            result.update(effect=False, effect_observation='not_executed')
        if isinstance(exc, ApprovalBindingError):
            result.update(binding_rejected=True, rejection_reason=str(exc))
    result['executed'] = executed
    print(json.dumps(result))


if __name__ == '__main__':
    main()
