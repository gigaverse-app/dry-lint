"""Run original ordering and budget admission on one complete frozen public campaign."""
import ast
from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace as NS

BASE = Path(__file__).resolve().parent


def definition(path, name, method_of=None):
    """Compile only an explicitly selected definition; never execute archive module bodies."""
    tree = ast.parse(path.read_text())
    nodes = tree.body
    if method_of:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == method_of).body
    node = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, str(path), 'exec')


def main():
    rows = json.loads((BASE / 'data/algorithm-input.json').read_text())['rows']
    originals = [r for r in rows if r['arm'] == 'current']
    features = {r['pair']: r for r in originals}
    pool = [NS(key=r['pair'], lane=r['lane'], priority=0, similarity=r['similarity'],
        new=NS(qualname=r['new']), existing=NS(qualname=r['existing'])) for r in originals]
    scope = {'Counter': Counter, 'estimate': lambda judge, cs, settings: sum(features[c.key]['estimated_usd'] for c in cs)}
    archive = BASE / 'data/archived-code'
    exec(definition(archive / 'run_experiment.py.txt', 'feature_order'), scope)
    exec(definition(archive / 'src/dry_lint/costs.py.txt', 'select', 'Ledger'), scope)
    result = {}
    current = set()
    for arm in ['current', 'fixed_feature', 'naive_cost', 'protected_cost']:
        ordered = scope['feature_order'](pool, arm, features, {})
        if arm == 'protected_cost':
            ordered = [c for c in ordered if c.key in current] + [c for c in scope['feature_order'](pool, 'naive_cost', features, {}) if c.key not in current]
        ledger = NS(settings=NS(budget=NS(usd=.04)), spent=0, usd=0, spend={})
        chosen = {ordered[i].key for i in scope['select'](ledger, NS(subscription=False), ordered)}
        if arm == 'current':
            current = chosen
        recorded = sorted([r for r in rows if r['arm'] == arm], key=lambda r: r['rank'])
        assert [c.key for c in ordered] == [r['pair'] for r in recorded]
        assert chosen == {r['pair'] for r in recorded if r['funded']}
        result[arm] = {'pool': len(pool), 'funded': len(chosen),
            'estimated_usd': sum(features[k]['estimated_usd'] for k in chosen),
            'useful_recording_case_funded': '25aaeb5894b0eda3' in chosen,
            'exact_order_and_funding_match': True}
    print(json.dumps({'scope': 'One complete public synthetic campaign; frozen full-background similarities, call-overlap features and normal costs. Original feature_order and Ledger.select executed; no index refit.', 'arms': result}, indent=2))


if __name__ == '__main__':
    main()
