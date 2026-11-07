#!/usr/bin/env python3
"""Replay selected source/answer/report decisions and published row aggregates, offline.

Does not encode, refit, regenerate background rankings, execute archived code or call a provider.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
POSITIVE = {'duplicate', 'drifted'}
def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
def read(name):
    p = HERE / name
    return json.loads(gzip.decompress(p.read_bytes()) if p.suffix == '.gz' else p.read_bytes())
def check(condition, message):
    if not condition:
        raise ValueError(message)
def report(decision, uncertain=False):
    if uncertain:
        return None
    return decision['label'] in POSITIVE and decision['score'] >= .8

def answer(observation):
    raw = observation['sanitized_response']
    check(sha(canonical(raw)) == observation['sanitized_response_sha256'], 'Sanitized response hash')
    if observation['kind'] == 'claude':
        check(raw['stop_reason'] == 'end_turn', 'Incomplete answer remains unknown')
        text = ''.join(b['text'] for b in raw['content'] if b['type'] == 'text')
        value = None
        for pos, char in enumerate(text):
            if char != '{':
                continue
            try:
                possible, _ = json.JSONDecoder().raw_decode(text, pos)
            except ValueError:
                continue
            if isinstance(possible, dict) and possible.get('label') in POSITIVE | {'separate'}:
                value = possible
                break
        check(value is not None and 0 <= value['score'] <= 1, 'Invalid recorded verdict')
    else:
        a = raw['answers']
        same, different = a['same_concept']['noul'], a['behaves_differently']['noul']
        reason = a['reason']['choice']
        boundary = max(a['separate_boundary']['noul'], a['reason']['probabilities'].get(reason, 0) if reason != 'portable' else 0)
        score = min(same, 1 - boundary) if boundary >= .5 else same
        value = dict(label='separate' if score < .6 else 'drifted' if different >= .8 else 'duplicate', score=round(score, 3), owner=a['owner']['choice'])
    for key in ('label', 'score', 'owner'):
        check(value.get(key, '') == observation['verdict'].get(key, ''), 'Original parser parity: ' + key)
    u = observation['usage']
    rates = (2, 10) if observation['kind'] == 'claude' else (.04, 0)
    cost = (u['input_tokens'] * rates[0] + u['output_tokens'] * rates[1]) / 1e6
    check(math.isclose(cost, observation['actual_usd'], abs_tol=1e-10), 'Usage/cost mismatch')
    return value, report(value)

def spans(value):
    if isinstance(value, dict):
        if 'evidence_id' in value and 'start_line' in value and 'end_line' in value:
            yield value
        for v in value.values():
            yield from spans(v)
    elif isinstance(value, list):
        for v in value:
            yield from spans(v)

def final(value, evidence):
    check(value['label'] in POSITIVE | {'separate'}, 'Final label')
    check(type(value['uncertainty']) is bool and 0 <= value['score'] <= 1, 'Final score/uncertainty')
    check(0 < len(value['citations']) <= 8, 'Citation requirement')
    for c in value['citations']:
        check(any(c['evidence_id'] == e['evidence_id'] and e['start_line'] <= c['start_line'] <= c['end_line'] <= e['end_line'] for e in evidence), 'Citation outside observed source')
    return report(value, value['uncertainty'])

def replay():
    data = read('data/recordings.json')
    source = read('data/source-files.json.gz')
    pins = {p['repository']: p for p in read('data/source-pins.json')}
    for h, blob in source.items():
        check(sha(blob['text']) == h, 'Source hash')
        pin = pins[blob['repository']]
        check(blob['revision'] == pin['revision'], 'Source pin')
        check(sha((HERE / pin['license_file']).read_bytes()) == pin['license_sha256'], 'License hash')
    result, paired = [], []
    for case in data['cases']:
        initial = []
        for proof in case['source_proofs']:
            f = case['candidate'][proof['side']]
            check(sha(f['code']) == proof['body_sha256'], 'Body hash')
            full = source[proof['file_sha256']]['text']
            region = '\n'.join(full.splitlines()[proof['line'] - 1:proof['end_line']])
            native = region.lstrip(' \t').removeprefix('export ').removeprefix('default ')
            check(f['code'] in (region, native, native + ';'), 'Native span mismatch: ' + case['id'])
            initial.append(dict(evidence_id='initial:' + proof['side'], start_line=proof['line'], end_line=proof['end_line']))
        if data['method'] == 'agentic-judge':
            q = case['corrected_body_request']
            check(canonical(q) == case['corrected_body_exact_rendered_json'], 'Exact rendered request')
            check(sha(canonical(q)) == case['corrected_body_wire_sha256'], 'Wire identity')
            check(sha(canonical(case['teacher_initial_request'])) == case['teacher_initial_request_sha256'], 'Teacher request')
            for side in ('new', 'existing'):
                check(case['candidate'][side]['code'] in q['messages'][0]['content'], 'Full source in body prompt')
            raw = case['corrected_body_response']
            calls = [b for b in raw['content'] if b['type'] == 'tool_use']
            check(raw['stop_reason'] == 'tool_use' and len(calls) == 1 and calls[0]['name'] == 'submit_verdict', 'Corrected terminal protocol')
            b = calls[0]['input']; t = case['teacher_submitted_final']
            before, after = final(b, initial), final(t, initial + list(spans(case['observable_tools'])))
            check(b == case['corrected_body']['decision'] and t == case['teacher']['decision'], 'Final observation parity')
            check(before == case['corrected_body']['reported'] and after == case['teacher']['reported'], 'Report parity')
            u = case['corrected_body']['usage']; cost = (u['input_tokens']*2 + u['output_tokens']*10)/1e6
            check(math.isclose(cost, case['corrected_body']['actual_cost_usd'], abs_tol=1e-10), 'Body cost')
            certain = before is not None and after is not None
            resolution = before is None and after is False and case['source_label'] in ('related', 'separate')
            paired.append(dict(id=case['id'], before=before, after=after, certain=certain, resolution=resolution, tiny=case['tiny_convenience'], body_cost=cost, teacher_cost=case['teacher']['actual_cost_usd']))
            for arm, v, emitted in [('corrected body', b, before), ('source tools', t, after)]:
                result.append(dict(case=case['id'], arm=arm, label=v['label'], score=v['score'], reported=emitted, source_label=case['source_label']))
        else:
            for o in case['observations']:
                check(sha(o['identity']['rendered_input']) == o['rendered_input_sha256'], 'Rendered input identity')
                # Claude supplies full function bodies; Jev's original contract caps bodies at 8000 characters.
                inp=o['identity']['rendered_input']
                if o['kind']=='claude':
                    for side in ('new','existing'):
                        check(case['candidate'][side]['code'] in inp, 'Full source in Claude prompt')
                else:
                    state=json.loads(inp)['state']
                    for side in ('new','existing'):
                        check(state[side+'_function']['code']==case['candidate'][side]['code'][:8000], 'Jev body rendering')
                v, emitted = answer(o)
                result.append(dict(case=case['id'], arm=o['kind'], label=v['label'], score=v['score'], reported=emitted, source_label=case['source_label']))
    metrics = dict(method=data['method'], source_files=len(source), selected_cases=len(data['cases']), replayed_decisions=len(result), scope='Recorded source, rendered input, answer parsing, citation/report policy and row aggregation. No full-corpus rank regeneration or new model outputs.')
    if data['method'] == 'agentic-judge':
        metrics.update(valid_body_finals=len(paired), certain_body=sum(r['before'] is not None for r in paired), uncertain_body=sum(r['before'] is None for r in paired), certain_teacher=sum(r['after'] is not None for r in paired), certain_pairs=sum(r['certain'] for r in paired), body_reports=sum(r['before'] is True for r in paired), teacher_reports=sum(r['after'] is True for r in paired), nonreport_uncertainty_resolutions=sum(r['resolution'] for r in paired), added_reports=sum(r['certain'] and r['after'] is True and r['before'] is False for r in paired), lost_reports=sum(r['certain'] and r['before'] is True and r['after'] is False for r in paired), body_actual_usd=round(sum(r['body_cost'] for r in paired),8), teacher_actual_usd=round(sum(r['teacher_cost'] for r in paired),8))
        check((metrics['valid_body_finals'],metrics['certain_body'],metrics['uncertain_body'],metrics['nonreport_uncertainty_resolutions'],metrics['added_reports'])==(9,6,3,2,0),'Corrected comparator counts')
    elif data['method'] == 'cpu-embeddings':
        p=read('data/paired-round2.json');hist=read('data/anonymous-regression-pairs.json')
        # Re-apply fixed Claude .8 policy to all 64 source-free observed scores, preserving missing answers.
        emissions=[]
        for r in p:
            v=r['provider_observations']['claude']
            emitted=report(v) if v['label'] is not None else None
            check(emitted==r['cpu_emission_projection'], 'All-64 emission projection')
            emissions.append(emitted)
        metrics.update(round2_pairs=len(p), reports=sum(e is True for e in emissions), nonreports=sum(e is False for e in emissions), unknown=sum(e is None for e in emissions), positive_revised_additions=sum(r['accepted_gold'] and r['label']=='duplicate' and r['direction']>0 for r in hist), positive_revised_losses=sum(r['accepted_gold'] and r['label']=='duplicate' and r['direction']<0 for r in hist))
        check((metrics['reports'],metrics['nonreports'],metrics['unknown'])==(1,35,28),'CPU full selected queue')
    else:
        p=read('data/paired-round2.json');original=residual=0
        for r in p:
            for o in r['observations']:
                emitted=report(o)
                check(emitted==o['original_diagnostic_report'], 'Original diagnostic projection')
                kept=emitted and bool(r['residual_candidate_included'])
                check(kept==o['residual_counterfactual_report'], 'Residual counterfactual')
                original+=int(emitted);residual+=int(kept)
        lost=[]
        for c in data['cases']:
            qualified=any(r['case']==c['id'] and r['reported'] for r in result)
            if qualified and c['source_label']=='useful' and c['original_funded'] and not c['residual_funded']:
                lost.append(c['id'])
        metrics.update(round2_pairs=len(p), round2_original_reporting_observations=original, round2_residual_reporting_observations=residual, reviewed_useful_opportunities_lost=len(lost), lost_case_ids=lost, rf14_native_concept=None, balanced_matched_answers=0)
        check(len(lost)==2, 'Two reviewed losses')
    return metrics,result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='Optional new output directory; package is read-only.')
    parser.add_argument('--case',help='Print an exact recorded representative case, including prompts and answers.')
    args=parser.parse_args()
    if args.case:
        case=next(c for c in read('data/recordings.json')['cases'] if c['id']==args.case)
        print(json.dumps(case,indent=2));return
    metrics,results=replay()
    if args.output:
        args.output.mkdir(parents=True,exist_ok=False)
        (args.output/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
        with (args.output/'paired-decisions.csv').open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(results[0]));writer.writeheader();writer.writerows(results)
    print(json.dumps(metrics,indent=2))
if __name__=='__main__':main()
