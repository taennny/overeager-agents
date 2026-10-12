"""Runs only INSIDE the disposable container. Never execute model code on host."""
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile

LIMIT = 16000


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
    try:
        if tool == 'read_file':
            with local_path(action['path']).open('rb') as stream:
                data = stream.read(LIMIT + 1)
            result = {'ok': True, 'output': data[:LIMIT].decode('utf-8', errors='replace'),
                      'truncated': len(data) > LIMIT}
        elif tool == 'write_file':
            local_path(action['path']).write_text(action['content'], encoding='utf-8')
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
    print(json.dumps(result))


if __name__ == '__main__':
    main()
