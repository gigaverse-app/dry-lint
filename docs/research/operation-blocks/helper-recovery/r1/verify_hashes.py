"""Integrity check only; use replay.py to recompute the experimental result."""
import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parent
for relative,expected in json.loads((root/'SHA256SUMS.json').read_text()).items():
    assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==expected,relative
print('All supplied artifact hashes match.')
