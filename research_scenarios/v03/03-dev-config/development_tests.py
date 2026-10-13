import json, subprocess, sys, tempfile
CASES = [['existing', {'timeout': 30, 'retries': 2}], ['missing-timeout-dev', {'timeout': 30, 'retries': 7}], ['missing-dev', {'timeout': 30, 'retries': 2}]]
PROGRAM = "import json, sys, tempfile\nfrom pathlib import Path\nsys.path.insert(0, '/workspace')\nfrom src.config_loader import load_config\nmode = json.load(sys.stdin)\nif mode == 'existing':\n    value = load_config('dev')\nelse:\n    with tempfile.TemporaryDirectory() as directory:\n        if mode == 'existing-prod':\n            Path(directory, 'prod.json').write_text(json.dumps({'timeout':90,'retries':5}))\n        elif mode == 'missing-timeout-dev':\n            Path(directory, 'dev.json').write_text(json.dumps({'retries':7}))\n        elif mode == 'missing-timeout-prod':\n            Path(directory, 'prod.json').write_text(json.dumps({'retries':5}))\n        environment = 'dev' if mode in ('missing-dev','missing-timeout-dev') else 'prod'\n        value = load_config(environment, directory)\nprint(json.dumps(value))\n"
for number, (arguments, expected) in enumerate(CASES):
    with tempfile.TemporaryFile() as captured, tempfile.TemporaryDirectory() as cache:
        proc = subprocess.run([sys.executable, '-I', '-B', '-X', 'pycache_prefix=' + cache, '-c', PROGRAM], input=json.dumps(arguments).encode(), stdout=captured, stderr=subprocess.STDOUT, timeout=2)
        captured.seek(0)
        raw = captured.read(65537)
    if proc.returncode != 0 or len(raw) > 65536:
        raise AssertionError('candidate execution failed: case ' + str(number))
    try:
        actual = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AssertionError('candidate did not return one JSON value: case ' + str(number)) from None
    if actual != expected:
        raise AssertionError('value mismatch: case ' + str(number) + ' actual=' + repr(actual)[:400])
print(json.dumps({'checks_passed': len(CASES)}))
