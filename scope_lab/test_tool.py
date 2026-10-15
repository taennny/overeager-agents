"""Host-owned, fixed development checks in a disposable read-only input snapshot.

The agent supplies no command, path or program. Only reviewed copy_paths leave
the agent container; the trusted development script stays outside its workspace.
Results are advisory: the independent final evaluator remains the task oracle.
"""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
from contextlib import contextmanager

from .oracle import relpath
from .sandbox import DockerSandbox, SandboxError

COPY_LIMIT = 1024 * 1024
FILE_LIMIT = 128 * 1024


class TestCleanupError(SandboxError):
    """A disposable test container could not be removed; stop the batch."""


@contextmanager
def staging_directory(event):
    directory = tempfile.TemporaryDirectory(prefix='scope-fixed-tests-')
    try:
        yield directory.name
    finally:
        try:
            directory.cleanup()
            event['staging_cleanup_ok'] = True
        except OSError:
            event['staging_cleanup_ok'] = False
            raise TestCleanupError('Fixed test snapshot cleanup failed') from None


def load_test_tool(path, fixture, scope):
    path = Path(path)
    config = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(config, dict) or set(config) !=
            {'version', 'copy_paths', 'script', 'timeout_seconds'} or
            config['version'] != 'fixed-tests-v0.1' or
            type(config['timeout_seconds']) is not int or not 1 <= config['timeout_seconds'] <= 20):
        raise ValueError('Invalid fixed test tool specification')
    paths = config['copy_paths']
    if (not isinstance(paths, list) or not paths or len(paths) > 64 or
            any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths)):
        raise ValueError('Fixed tests require unique exact copy paths')
    for value in paths:
        relpath(value)
        # No protected input is copied even if also present in allowed rules.
        from .oracle import matches
        if any(matches(value, r['path']) for r in scope['protected']):
            raise ValueError('Test copy list contains a protected resource')
        target = Path(fixture) / value
        if not target.is_file() or target.is_symlink():
            raise ValueError('Missing regular test input')
        for parent in target.parents:
            if parent == Path(fixture):
                break
            if parent.is_symlink():
                raise ValueError('Linked test input directory')
    relpath(config['script'])
    script_path = path.parent / config['script']
    if (script_path.is_symlink() or path.parent.resolve() not in script_path.resolve().parents or
            Path(fixture).resolve() in script_path.resolve().parents):
        raise ValueError('Trusted development checks must be outside the agent fixture')
    script = script_path.read_text(encoding='utf-8')
    if len(script.encode()) > 32000:
        raise ValueError('Development script too large')
    return dict(config, script_text=script,
                script_sha256=hashlib.sha256(script.encode()).hexdigest())


class FixedTestTool:
    def __init__(self, source, config, image):
        self.source, self.config, self.image = source, config, image
        self.events = []

    def __call__(self, timeout):
        collected = self.source.tool({'tool': '_collect_test_files',
                                      'paths': self.config['copy_paths']}, min(timeout, 5))
        if not collected.get('ok'):
            return {'ok': False, 'executed': False, 'error': 'test_input_rejected',
                    'output': 'Test inputs must be regular files without links.'}
        files = collected.get('files')
        if not isinstance(files, dict) or set(files) != set(self.config['copy_paths']):
            raise SandboxError('Malformed test input collection')
        payload = {}
        for name, encoded in files.items():
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise SandboxError('Malformed test input encoding') from None
            if len(content) > FILE_LIMIT:
                raise SandboxError('Test input size limit exceeded')
            payload[name] = content
        if sum(map(len, payload.values())) > COPY_LIMIT:
            raise SandboxError('Test input copy budget exceeded')
        box = DockerSandbox(self.image)
        event = {'input_sha256': {n: hashlib.sha256(v).hexdigest() for n, v in payload.items()},
                 'script_sha256': self.config['script_sha256'], 'copied_paths': sorted(payload),
                 'container': box.name, 'writeback': False}
        self.events.append(event)
        # Freeze a new host-owned staging snapshot, never mount the original
        # fixture, source container volume, protection targets or grading files.
        with staging_directory(event) as directory:
            root = Path(directory)
            root.chmod(0o755)
            for name, content in payload.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(0o444)
            for parent in root.rglob('*'):
                if parent.is_dir():
                    parent.chmod(0o755)
            try:
                box.start_readonly_inputs(root)
                result = box.evaluate(self.config['script_text'],
                                      timeout=min(timeout, self.config['timeout_seconds']))
                result['executed'] = True
                event.update(returncode=result.get('returncode'), timed_out=result.get('timed_out'),
                             truncated=result.get('truncated'), image_id=box.image_id)
            finally:
                # Cleanup exceptions propagate and invalidate the harness trial.
                try:
                    box.close()
                    event['cleanup_ok'] = True
                except SandboxError:
                    event['cleanup_ok'] = False
                    raise TestCleanupError('Fixed test container cleanup failed') from None
        result['test_run'] = event
        result['advisory_only'] = True
        return result
