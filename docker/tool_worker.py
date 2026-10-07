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

LIMIT = 16000


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


def main():
    action = json.loads(sys.stdin.read(70000))
    tool = action['tool']
    executed = False
    try:
        if '_permitted_targets' in action:
            target = local_path(action['path']).relative_to('/workspace').as_posix()
            if target not in action['_permitted_targets']:
                raise ValueError('Resolved target outside policy')
        if tool == '_collect_test_files':
            result = collect_test_files(action['paths'])
        elif tool == 'read_file':
            path = local_path(action['path'])
            executed = True
            with path.open('rb') as stream:
                data = stream.read(LIMIT + 1)
            result = {'ok': True, 'output': data[:LIMIT].decode('utf-8', errors='replace'),
                      'truncated': len(data) > LIMIT}
        elif tool == 'write_file':
            path = local_path(action['path'])
            executed = True
            path.write_text(action['content'], encoding='utf-8')
            result = {'ok': True, 'output': 'written'}
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
    result['executed'] = executed
    print(json.dumps(result))


if __name__ == '__main__':
    main()
