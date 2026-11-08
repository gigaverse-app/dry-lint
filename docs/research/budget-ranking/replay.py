"""Provider-free replay of frozen admissions and recorded answers (Python 3.11+)."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load():
    return json.loads(gzip.decompress((BASE / 'data/recordings.json.gz').read_bytes()))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parsed_answer(observation):
    """Reparse original Claude text; held inputs retain only the recorded numeric verdict."""
    verdict = observation.get('verdict')
    raw = observation.get('raw_provider')
    if not raw or observation['kind'] != 'claude':
        return verdict
    assert sha(raw['text'].encode()) == raw['sha256']
    response = json.loads(raw['text'])
    text = ''.join(block.get('text', '') for block in response.get('content', []) if block.get('type') == 'text')
    decoder = json.JSONDecoder()
    parsed = None
    for position, character in enumerate(text):
        if character != '{':
            continue
        try:
            value, _ = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and 'label' in value:
            parsed = value
            break
    if verdict is None:
        # Paid malformed answers remain unknown; a transport error may contain no content.
        assert parsed is None or observation.get('error')
        return None
    assert parsed is not None, 'Recorded successful answer must parse'
    assert parsed['label'] == verdict['label']
    assert float(parsed.get('score', 1)) == verdict['score']
    return parsed


def reports(verdict):
    if verdict is None:
        return None
    return verdict['label'] != 'separate' and float(verdict['score']) >= 0.80


def baseline(arm):
    return arm in {'baseline', 'current', 'function-only'}


def category(case):
    review = case['source_review']
    return review.get('category', review.get('separate_interpretive_category', review.get('source_label', review.get('label', 'unknown'))))


def replay(cases):
    panels = {}
    paid = {}
    for case in cases:
        panel = panels.setdefault(case['panel'], {'cases': 0, 'public_payloads': 0, 'source_free_holds': 0,
            'known_claude': 0, 'unknown_claude': 0, 'novel_answers': 0, 'novel_unknowns': 0,
            'novel_reports': 0, 'treatment_only_pairs': 0, 'treatment_only_reports': 0,
            'arms': {}, 'source_categories': collections.Counter()})
        panel['cases'] += 1
        panel['public_payloads' if case['redistribution'] == 'public' else 'source_free_holds'] += 1
        panel['source_categories'][category(case) or 'unknown'] += 1
        for observation in case['observations']:
            identity = observation['identity']
            if 'rendered_input' in identity:
                assert sha(identity['rendered_input'].encode()) == observation['rendered_sha256']
                assert sha(json.dumps(identity, sort_keys=True).encode()) == observation['request_key']
            if not observation.get('cached') and observation.get('usd') is not None:
                key = observation['request_key']
                value = (case['round'], observation['usd'])
                assert key not in paid or paid[key] == value
                paid[key] = value
        claude = next(o for o in case['observations'] if o['kind'] == 'claude')
        verdict = parsed_answer(claude)
        emitted = reports(verdict)
        panel['known_claude' if emitted is not None else 'unknown_claude'] += 1
        if case['role'] == 'novel':
            panel['novel_answers' if emitted is not None else 'novel_unknowns'] += 1
            panel['novel_reports'] += emitted is True
        by_arm = collections.defaultdict(list)
        for admission in case['admissions']:
            by_arm[admission['arm']].append(admission)
            if 'policy_would_emit' in admission:
                calculated = bool(admission['funded'] and emitted) if emitted is not None else None
                assert calculated == admission['policy_would_emit'], (case['id'], admission)
        base_funded = any(a['funded'] for arm, rows in by_arm.items() if baseline(arm) for a in rows)
        treat_funded = any(a['funded'] for arm, rows in by_arm.items() if not baseline(arm) and 'model' not in arm for a in rows)
        is_function = case['packet'].get('candidate_kind', 'function') != 'model'
        if not base_funded and treat_funded and is_function:
            panel['treatment_only_pairs'] += 1
            panel['treatment_only_reports'] += emitted is True
        for arm, rows in by_arm.items():
            funded = any(a['funded'] for a in rows)
            row = panel['arms'].setdefault(arm, {'funded': 0, 'known_reports': 0, 'unknown_funded': 0,
                'useful_reports': 0, 'related_reports': 0, 'source_unknown_reports': 0})
            row['funded'] += funded
            row['known_reports'] += funded and emitted is True
            row['unknown_funded'] += funded and emitted is None
            if funded and emitted is True:
                label = category(case)
                row['useful_reports'] += label in {'useful', 'bounded_extraction', 'duplicate'}
                row['related_reports'] += label in {'related', 'already_shared'}
                row['source_unknown_reports'] += label in {None, 'unknown'}
    costs = collections.defaultdict(float)
    for round_number, cost in paid.values():
        costs[str(round_number)] += cost
    return {'scope': 'Recorded admissions and answers; no retrieval rebuild or provider execution. Held records replay numeric verdicts only.',
        'panels': panels, 'actual_paid_usd_by_round': {k: round(v, 8) for k, v in costs.items()},
        'unique_paid_requests': len(paid),
        'separate_private_aggregates': json.loads((BASE / 'data/private-aggregates.json').read_text())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', help='Print one public case including exact inputs, original answers, admissions and source review')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cases = load()
    result = next(c for c in cases if c['id'] == args.case) if args.case else replay(cases)
    output = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end='')


if __name__ == '__main__':
    main()
