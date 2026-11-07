"""Standard-library-only reading of immutable public recordings."""
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
POS = {'duplicate', 'drifted'}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def digest(value):
    return sha(canonical(value))


def read(name):
    path = HERE / name
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


def cost(q, response):
    usage = response['usage']
    if response['model'] != q['model']:
        raise ValueError('Response model mismatch')
    for key in ('input_tokens', 'output_tokens'):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise ValueError('Unknown token usage')
    if any(usage.get(key, 0) for key in ('cache_read_input_tokens', 'cache_creation_input_tokens')):
        raise ValueError('Unexpected cached usage')
    a, b = q['reservation_rates_per_million']
    return round((usage['input_tokens'] * a + usage['output_tokens'] * b) / 1e6, 12)


def verdict(q, response):
    if q['kind'] == 'claude':
        if response.get('stop_reason') != 'end_turn':
            raise ValueError('Incomplete Claude answer')
        text = ''.join(b['text'] for b in response['content'] if b['type'] == 'text')
        # The frozen parser accepts the first complete JSON verdict, including fenced JSON.
        for i, char in enumerate(text):
            if char != '{':
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get('label') in POS | {'separate'} and 'score' in value:
                if not 0 <= value['score'] <= 1:
                    raise ValueError('Invalid score')
                value.setdefault('owner', '')
                value.setdefault('why', '')
                return value, False
        raise ValueError('No valid JSON verdict')
    answers = response['answers']
    same = answers['same_concept']['noul']
    differs = answers['behaves_differently']['noul']
    reason = answers['reason']['choice']
    rejection = answers['reason']['probabilities'].get(reason, 0) if reason != 'portable' else 0
    separation = max(answers['separate_boundary']['noul'], rejection)
    score = min(same, 1 - separation) if separation >= .5 else same
    why = read('prompts.json')['jev_generated_reasons'][reason]
    if score >= .8 and reason != 'portable':
        why = 'One concept may be shared, but dependency contracts need review before consolidation.'
    return dict(label='separate' if score < .6 else 'drifted' if differs >= .8 else 'duplicate',
                score=round(score, 3), behaves_differently=round(differs, 3),
                owner=answers['owner']['choice'], why=why), reason == 'uncertain'


def prompt(candidate):
    text = read('prompts.json')['claude_shared_operations']
    for side in ('new', 'existing'):
        f = candidate[side]
        name = f['path'] + '::' + ((f['owner'] + '.') if f.get('owner') else '') + f['name']
        text = text.replace('<<' + side + '_name>>', name).replace('<<' + side + '_code>>', f['code'])
    if candidate.get('policies'):
        text += '\nADOPTER POLICIES (configured rules and declared roles; verify applicability against source):\n'
        text += json.dumps(candidate['policies'], ensure_ascii=True)
    return text


def jev_state(candidate):
    state = {}
    for side in ('new', 'existing'):
        f = candidate[side]
        state[side + '_function'] = dict(
            name=((f['owner'] + '.') if f.get('owner') else '') + f['name'],
            module=f['path'].removesuffix('.py').replace('/', '.'),
            code=f['code'][:8000], code_truncated=len(f['code']) > 8000,
            repository=f['origin']['repository'] if f.get('origin') else '',
            source_context=f['context'])
    state['consolidation'] = candidate['consolidation']
    if candidate.get('policies'):
        state['adopter_policies'] = candidate['policies']
    return state
