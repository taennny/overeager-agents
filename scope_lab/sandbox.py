"""Docker-only execution. No host-shell fallback, original-workspace mounts,
credentials or Docker socket. Fixed tests mount only a new selected-input copy.
"""
import json
import io
from pathlib import Path
import subprocess
import tarfile
import uuid


class SandboxError(RuntimeError):
    pass


class DockerSandbox:
    def __init__(self, image='overeager-sandbox:week1'):
        self.image = image
        self.name = 'scope-' + uuid.uuid4().hex
        self.created = False
        self.stopped = False

    def _docker(self, args, data=None, timeout=40):
        try:
            proc = subprocess.run(['docker'] + args, input=data, text=not isinstance(data, bytes), capture_output=True,
                                  timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxError('Docker unavailable or operation timed out: ' + type(exc).__name__) from None
        if isinstance(proc.stdout, bytes):
            proc.stdout = proc.stdout.decode('utf-8', errors='replace')
            proc.stderr = proc.stderr.decode('utf-8', errors='replace')
        if proc.returncode:
            raise SandboxError('Docker operation failed: ' + args[0] + '; ' + proc.stderr[-1500:])
        return proc.stdout

    def start(self, fixture):
        # Require an explicit build; experiments never silently pull a newer image.
        self.image_id = self._docker(['image', 'inspect', '--format', '{{.Id}}', self.image]).strip()
        self._docker(['create', '--name', self.name, '--network', 'none', '--read-only',
                      '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                      '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
                      '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m',
                      '--user', '10001:10001', '--workdir', '/workspace', self.image_id])
        self.created = True
        # Preserve fixture modes but assign archive ownership to the sandbox UID.
        # The archive is built only from the operator-selected fixture, not output.
        def owner(info):
            info.uid = info.gid = 10001
            info.uname = info.gname = ''
            return info
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w', dereference=False) as tar:
            for child in sorted(Path(fixture).iterdir()):
                tar.add(str(child), arcname=child.name, filter=owner)
        self._docker(['cp', '-a', '-', self.name + ':/workspace/'], data=archive.getvalue())
        self._docker(['start', self.name])

    def start_readonly_inputs(self, staging):
        """Only for a host-created snapshot of selected development inputs."""
        self.image_id = self._docker(['image', 'inspect', '--format', '{{.Id}}', self.image]).strip()
        self._docker(['create', '--name', self.name, '--network', 'none', '--read-only',
                      '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                      '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
                      '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m',
                      '--mount', 'type=bind,src=' + str(Path(staging).resolve()) + ',dst=/workspace,readonly',
                      '--user', '10001:10001', '--workdir', '/workspace', self.image_id])
        self.created = True
        self._docker(['start', self.name])

    def tool(self, action, timeout):
        request = dict(action)
        request['timeout_seconds'] = timeout
        raw = self._docker(['exec', '-i', self.name, 'python', '-I', '/opt/scope/tool_worker.py'],
                           data=json.dumps(request), timeout=timeout + 8)
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or type(value.get('ok')) is not bool:
                raise ValueError()
        except ValueError:
            raise SandboxError('Malformed tool observation') from None
        return value

    def export(self, target, stop=True):
        if stop and not self.stopped:
            # Kill the entire container, including detached child processes, before
            # collecting final state. docker cp supports stopped containers.
            self._docker(['kill', self.name])
            self.stopped = True
        target = Path(target)
        target.mkdir(parents=True, exist_ok=False)
        self._docker(['cp', self.name + ':/workspace/.', str(target)])

    def evaluate(self, script, timeout=10):
        # Evaluation takes place in a SECOND container, with a restored final
        # workspace and the trusted evaluator supplied by the host over stdin.
        raw = self._docker(['exec', '-i', self.name, 'python', '-I', '/opt/scope/tool_worker.py'],
                           data=json.dumps({'tool': 'shell', 'command': 'python -I -c ' +
                               __import__('shlex').quote(script), 'timeout_seconds': timeout}), timeout=timeout + 8)
        return json.loads(raw)

    def close(self):
        if self.created:
            self._docker(['rm', '-f', '-v', self.name])
            self.created = False
