"""Find or copy exact study backgrounds from a separately cloned pinned goldens repository."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent
PIN = 'bb29c4b71987008d06c2381a68b6833b6d542e3e'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--goldens', type=Path, help='Existing separate clone; no fetch is performed')
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    lookup = json.loads((BASE / 'data/background-catalog-lookup.json').read_text())
    if not a.goldens:
        print(json.dumps(lookup, indent=2))
        return
    if not a.out:
        p.error('--goldens requires --out')
    for row in lookup['study_backgrounds']:
        if not row['catalog_matches']:
            continue
        digest = row['sha256']
        object_path = f'objects/sha256/{digest[:2]}/{digest[2:]}'
        data = subprocess.check_output(['git', '-C', str(a.goldens), 'show', PIN + ':' + object_path])
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit('Exact background checksum mismatch')
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / (digest + '.json.gz')).write_bytes(data)
    print('Copied exact catalog matches only; missing and held inputs remain unavailable.')


if __name__ == '__main__':
    main()
