"""Verify the portable replay, original algorithm example, integrity, safety and links."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

BASE = Path(__file__).resolve().parent


def main():
    manifest = BASE / 'SHA256SUMS'
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            digest, name = line.split('  ', 1)
            assert hashlib.sha256((BASE / name).read_bytes()).hexdigest() == digest, name
    spec = importlib.util.spec_from_file_location('recorded_replay', BASE / 'replay.py')
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    cases = replay.load()
    result = replay.replay(cases)
    assert result == json.loads((BASE / 'data/expected-replay.json').read_text())
    # The reporting boundary must preserve missing answers and reject separate/high-score verdicts.
    assert replay.reports(None) is None
    assert not replay.reports({'label': 'separate', 'score': 1})
    assert not replay.reports({'label': 'duplicate', 'score': .79})
    assert replay.reports({'label': 'duplicate', 'score': .8})
    for case in cases:
        if case['redistribution'] == 'held':
            assert 'candidate' not in case['packet']
            for proof in case['packet']['source_proofs']:
                assert not {'excerpt', 'code', 'context'} & proof.keys()
            for observation in case['observations']:
                assert 'raw_provider' not in observation
                assert 'rendered_input' not in observation['identity']
                assert not observation['verdict'] or 'why' not in observation['verdict']
    sources = json.loads(gzip.decompress((BASE / 'data/selected-source-files.json.gz').read_bytes()))
    allowed = {'BerriAI/litellm', 'pingdotgg/t3code', 'anomalyco/opencode', 'OpenHands/software-agent-sdk'}
    for source in sources:
        assert source['repository'] in allowed
        assert 'enterprise' not in Path(source['path']).parts
        assert hashlib.sha256(source['text'].encode()).hexdigest() == source['sha256']
    algorithm = subprocess.run([sys.executable, '-I', str(BASE / 'algorithm.py')], cwd=BASE, check=True, capture_output=True, text=True)
    assert json.loads(algorithm.stdout)
    scanned = 0
    for path in BASE.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        data = path.read_bytes()
        if path.suffix == '.gz':
            data = gzip.decompress(data)
        text = data.decode()
        scanned += 1
        for pattern in [r'gigaverse-(?:ai|backend|web-app|mobile)', r'AI32\d\d',
                        r'gh[pousr]_[A-Za-z0-9]{30,}', r'sk-(?:ant-)?[A-Za-z0-9_-]{30,}',
                        r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----']:
            assert not re.search(pattern, text), (str(path.relative_to(BASE)), 'sensitive pattern')
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if target.startswith(('https://', 'http://', '#')):
                    continue
                target = target.split('#')[0]
                assert (path.parent / target).exists(), (path.name, target)
    print(json.dumps({'status': 'PASS', 'cases': len(cases), 'selected_full_files': len(sources),
        'files_scanned_including_decompressed_archives': scanned,
        'checks': ['raw public Claude answer parsing and policy replay', 'recorded aggregate equality',
                   'original algorithm example', 'unknown and threshold boundaries', 'held-source exclusion',
                   'full source hashes', 'local Markdown links', 'sensitive-pattern scan including gzip', 'SHA256SUMS'],
        'external_links': 'Proposed branch URLs are syntactically checked in handoff; not live until root publishes.'}, indent=2))


if __name__ == '__main__':
    main()
