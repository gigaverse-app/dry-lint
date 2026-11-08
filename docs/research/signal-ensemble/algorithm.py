"""Execute the original operational gate on the exact public Azure case's frozen background state."""
import ast
import collections
import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    p = BASE / 'data/archived-code/funded-rounds/round2/operation_gate.py.txt'
    tree = ast.parse(p.read_text())
    # Original module has just this constant and class; do not run archived imports/top-level harnesses.
    tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef) or isinstance(n, ast.Assign)]
    scope = {'collections': collections, 'math': math}
    exec(compile(tree, str(p), 'exec'), scope)
    state = json.loads((BASE / 'data/algorithm-input.json').read_text())
    gate = scope['OperationalGate'].__new__(scope['OperationalGate'])
    for key in ['ids', 'paths', 'idf', 'df', 'mass', 'rare_max']:
        setattr(gate, key, state[key])
    gate.ops = [frozenset(s) for s in state['ops']]
    gate.memo = {}
    stats = gate.stats(0, 1)
    for key, value in stats.items():
        wanted = state['expected'][key]
        assert abs(value-wanted) < 1e-12 if isinstance(value, float) else value == wanted
    passing = gate.passing(0, 1, state['raw_cosine'], state['dense_cosine'])
    assert passing
    print(json.dumps({'case': state['case'], 'original_gate_pass': passing, 'stats': stats,
        'full_background_documents': state['full_background_documents'],
        'scope': 'Original stats/passing methods over exact full-background token/IDF/DF/mass projection; no two-snippet refit or new dense embedding. Recorded model/source replay follows separately.'}, indent=2))


if __name__ == '__main__':
    main()
