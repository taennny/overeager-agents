"""Local implementation identity, including uncommitted source changes."""
import hashlib
import json
from pathlib import Path


def implementation_hash():
    root = Path(__file__).resolve().parents[1]
    files = [p for folder in ('scope_lab', 'docker') for p in sorted((root/folder).glob('*.py'))]
    files.append(root/'docker/Dockerfile')
    contents = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()
