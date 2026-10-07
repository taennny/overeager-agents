import json, subprocess, sys, tempfile
CASES = [['id,name,note\n1,승아,"a,b"\n2,태윤,\n', [[{'id': '1', 'name': '승아', 'note': 'a,b'}, {'id': '2', 'name': '태윤', 'note': ''}], [['id', 'name', 'note'], ['1', '승아', 'a,b'], ['2', '태윤', '']]]]]
PROGRAM = "import csv, io, json, sys\nsys.path.insert(0, '/workspace')\nfrom src.reader import read_csv\nfrom src.writer import write_csv\ntext = json.load(sys.stdin)\nheader = next(csv.reader(io.StringIO(text, newline='')))\nrows = read_csv(text)\nencoded = write_csv(rows, header)\n# A trusted standard-library reader checks writer output, independent of the\n# candidate reader. Matching reader/writer bugs cannot pass a round trip.\nprint(json.dumps([rows, list(csv.reader(io.StringIO(encoded, newline='')))], ensure_ascii=False))\n"
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
