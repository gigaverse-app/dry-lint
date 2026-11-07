"""Execute the original Python contract-operation matcher on native public functions and resolved links."""
import ast
import hashlib
import json
from pathlib import Path
import re
import textwrap
from types import SimpleNamespace as NS

BASE = Path(__file__).resolve().parent


def function(record):
    value = dict(record)
    value['qualname'] = value['path'] + '::' + (value['owner'] + '.' if value.get('owner') else '') + value['name']
    value['analysis'] = NS(**value['analysis']) if value.get('analysis') else None
    return NS(**value)


def main():
    p = BASE / 'data/archived-code/funded-rounds/contract_operations.py.txt'
    tree = ast.parse(p.read_text())
    # Explicit stdlib globals; omit the TypeScript import, which this Python selected case does not use.
    tree.body = [n for n in tree.body if isinstance(n, (ast.Assign, ast.FunctionDef, ast.ClassDef))]
    scope = {'ast': ast, 'hashlib': hashlib, 'json': json, 're': re, 'textwrap': textwrap}
    exec(compile(tree, str(p), 'exec'), scope)
    state = json.loads((BASE / 'data/algorithm-input.json').read_text())
    result = scope['match'](scope['Signatures'](), function(state['new']), function(state['existing']),
        state['canonical_model'], state['new_link'], state['existing_link'], set(state['model']['declaration']['fields']))
    assert result == state['expected'], (result, state['expected'])
    print(json.dumps({'case': state['case'], 'result': result,
        'scope': 'Original Python signature normalization/matching over exact source and frozen resolved links; matches all original context hashes and source lines. No corpus retrieval or ownership-link reconstruction.'}, indent=2))


if __name__ == '__main__':
    main()
