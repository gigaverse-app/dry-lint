"""Hydrate exact files from existing local Git objects, or one held case from its original ledger."""
import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository', help='Exact public repository name in source-manifest.json')
    p.add_argument('--git', type=Path, help='Existing checkout or bare repository; never fetches')
    p.add_argument('--case', help='Held case to hydrate from the exact original ledger')
    p.add_argument('--ledger', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.case:
        if not a.ledger:
            p.error('--case requires --ledger')
        cases = json.loads(gzip.decompress((BASE / 'data/recordings.json.gz').read_bytes()))
        case = next(c for c in cases if c['id'] == a.case)
        raw = a.ledger.read_bytes()
        if sha(raw) != case['provenance']['sha256']:
            raise SystemExit('Ledger SHA256 mismatch; no cross-revision or fuzzy hydration')
        record = next(json.loads(line) for line in raw.splitlines() if json.loads(line).get('id') == a.case)
        assert record['packet']['repository'] == case['packet']['repository']
        assert record['packet']['revision'] == case['packet']['revision']
        for observed in case['observations']:
            original = next(o for o in record['observations'] if o['kind'] == observed['kind'])
            assert sha(original['identity']['rendered_input'].encode()) == observed['rendered_sha256']
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(record, indent=2) + '\n')
        print('Hydrated one exact local case; redistribution hold still applies.')
        return
    if not a.repository or not a.git:
        p.error('Supply --repository and --git, or --case and --ledger')
    manifest = json.loads((BASE / 'data/source-manifest.json').read_text())
    files = [s for s in manifest if s['repository'] == a.repository]
    if not files:
        raise SystemExit('Repository is not in this publication')
    for source in files:
        raw = subprocess.check_output(['git', '-C', str(a.git), 'show', source['revision'] + ':' + source['path']])
        if sha(raw) != source['sha256']:
            raise SystemExit('Source SHA256 mismatch: ' + source['path'])
        target = a.out / source['revision'] / source['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    print(f'Hydrated {len(files)} exact files; no network requests.')


if __name__ == '__main__':
    main()
