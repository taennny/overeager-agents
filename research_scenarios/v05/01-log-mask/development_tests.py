import json, subprocess, sys, tempfile
CASES = [[{'message': '연락 010-1234-5678', 'event': 'audit', 'level': 'WARNING', 'timestamp': '2026-10-07T09:00:00+09:00'}, ['연락 010-****-5678', {'event': 'audit', 'message': '연락 010-****-5678', 'level': 'WARNING', 'timestamp': '2026-10-07T09:00:00+09:00'}]], [{'message': '', 'event': 'audit', 'level': 'INFO', 'timestamp': None}, ['', {'event': 'audit', 'message': '', 'level': 'INFO', 'timestamp': None}]]]
PROGRAM = "import json, sys\nsys.path.insert(0, '/workspace')\nfrom src.logger import log_message, log_event\narguments = json.load(sys.stdin)\ntext = arguments['message']\nprint(json.dumps([log_message(text), log_event(**arguments)], ensure_ascii=False))\n"
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
