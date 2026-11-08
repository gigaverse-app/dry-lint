#!/usr/bin/env python3
"""Portable recorded-answer replay; no network, environment credentials or lab imports."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent

def read(name):
    p = HERE / name
    raw = p.read_bytes()
    return json.loads(gzip.decompress(raw) if p.suffix == '.gz' else raw)

def rows(name):
    return [json.loads(s) for s in (HERE / name).read_text().splitlines() if s.strip()]

def sha(raw):
    return hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).hexdigest()

def emit(label, score, settings):
    return label != 'separate' and score >= settings['report_at']

def parse(o):
    """Frozen Jev contextual scoring / Claude JSON final answer, without transport."""
    raw = o['response']
    if raw is None:
        return None
    if o['kind'] == 'jev':
        a = raw['answers']; s = o['identity']['settings']
        same = float(a['same_concept']['noul'])
        differs = float(a['behaves_differently']['noul'])
        reason = a['reason']['choice']
        rejection = float(a['reason'].get('probabilities', {}).get(reason, 0)) if reason != 'portable' else 0
        separation = max(float(a['separate_boundary']['noul']), rejection)
        score = min(same, 1 - separation) if separation >= .5 else same
        label = 'separate' if score < s['drop_below'] else 'drifted' if differs >= s['drift_at'] else 'duplicate'
        return {'label': label, 'score': round(score, 3), 'behaves_differently': round(differs, 3), 'owner': a['owner'].get('choice', '')}
    text = ''.join(b['text'] for b in raw['content'])
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    # Same first-object boundary as the frozen command parser for these selected answers.
    match = re.search(r'\{.*\}', text, re.S)
    return json.loads(match.group())

def replay():
    cases = read('data/selected-cases.json.gz')
    checked = []
    for c in cases:
        for o in c['observations']:
            ident = o['identity']
            assert sha(json.dumps(ident, sort_keys=True, ensure_ascii=True, allow_nan=False)) == o['request_key']
            v = parse(o); want = o['recorded_verdict']
            assert v is not None and want is not None, 'Selected answer missing; unknown is not negative'
            for k in ('label', 'score', 'owner'):
                assert v.get(k, '') == want.get(k, ''), (c['id'], o['kind'], k, v, want)
            checked.append({'id': c['id'], 'kind': o['kind'], 'label': v['label'], 'score': v['score'], 'reportable': emit(v['label'], v['score'], ident['settings'])})
    obs = rows('data/observations.jsonl'); totals = []
    admissions = {(r['round'], r['id']): r for r in rows('data/policy-admissions.jsonl')}
    counts = Counter()
    for o in obs:
        p = admissions.get((o['round'], o['id']))
        known = o['label'] is not None and o['state'] == 'success'
        reportable = emit(o['label'], o['score'], o['policy']) if known else None
        if p:
            for profile, a in p['profiles'].items():
                key = (o['round'], profile, o['kind'], o['role'])
                counts[key + ('unknown',)] += reportable is None
                if reportable is not None:
                    b = bool(a['baseline_funded'] and reportable); v = bool(a['variant_funded'] and reportable)
                    counts[key + ('baseline',)] += b; counts[key + ('variant',)] += v
                    counts[key + ('added',)] += v and not b; counts[key + ('lost',)] += b and not v
    for rn in (1, 2):
        rr = [o for o in obs if o['round'] == rn]
        paid = sum((Decimal(str(o['actual_usd'])) for o in rr if not o['cached'] and o['actual_usd'] is not None), Decimal(0))
        totals.append({'round': rn, 'requests_in_primary_feed': len(rr), 'successful': sum(o['state'] == 'success' for o in rr), 'unknown': sum(o['state'] != 'success' for o in rr), 'primary_feed_actual_usd': str(paid.quantize(Decimal('.00000001')))})
    result = {'selected_raw_answers_reparsed': len(checked), 'selected_answers': checked, 'primary_feeds': totals,
              'policy_counts': [{'round': k[0], 'profile': k[1], 'kind': k[2], 'role': k[3], **{x: counts[k + (x,)] for x in ['baseline','variant','added','lost','unknown']}} for k in sorted({k[:4] for k in counts})],
              'limits': 'Replays final answers and fixed admission records; does not refit whole-corpus retrieval or independently prove source truth. Primary feed costs exclude separately attributed current-phase usage. Jev and Claude remain separate.'}
    return result

def audit():
    patterns = [r'sk-ant-[A-Za-z0-9_-]{20,}',r'sk-proj-[A-Za-z0-9_-]{20,}',r'gh[pousr]_[A-Za-z0-9]{30,}',r'github_pat_[A-Za-z0-9_]{40,}',r'AKIA[0-9A-Z]{16}',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'gigaverse-(?:app|ai)/(?:gigaverse-backend|backend-common)',r'gigaverse[/]core[/]']
    failures=[]; files=0; compressed=0; links=0
    for p in sorted(HERE.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts or any(x.startswith('local-') for x in p.relative_to(HERE).parts): continue
        raw=p.read_bytes();files+=1
        if p.suffix=='.gz': raw=gzip.decompress(raw);compressed+=1
        text=raw.decode()
        for pat in patterns:
            if re.search(pat,text): failures.append((str(p.relative_to(HERE)),'sensitive pattern '+pat))
        if p.suffix=='.md':
            for target in re.findall(r'\]\(([^)]+)\)',text):
                if target.startswith(('http:','https:','#','mailto:')): continue
                target=target.split('#')[0]
                if target and not (p.parent/target).exists():failures.append((str(p.relative_to(HERE)),'missing link '+target))
                links+=1
    data=read('data/source-files.json.gz')
    for h,txt in data['blobs'].items(): assert sha(txt)==h
    licensed={p['repository'] for p in read('data/source-pins.json') if 'license_file' in p}
    assert all(p['repository'] in licensed for p in data['files'])
    for c in read('data/selected-cases.json.gz'):
        assert c['repository'] in licensed
        for o in c['observations']:
            response=o['response'] or {}
            assert set(response)<= {'model','stop_reason','answers','content','usage'}
            assert all(b['type']=='text' for b in response.get('content',[]))
    if (HERE/'SHA256SUMS').exists():
        for line in (HERE/'SHA256SUMS').read_text().splitlines():
            h,name=line.split('  ',1);assert sha((HERE/name).read_bytes())==h,name
    if failures: raise SystemExit(json.dumps(failures,indent=2))
    return {'status':'PASS','files_scanned':files,'compressed_archives_opened':compressed,'relative_links_checked':links,'credential_or_private_identifier_matches':0,'source_files_verified':len(data['files']),'limit':'Pattern scan plus allowlisted response/source export; not a universal secret detector.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['replay','inspect','archive','audit']);p.add_argument('name',nargs='?');p.add_argument('--part',choices=['all','source','prompt','answer'],default='all');a=p.parse_args()
    if a.command=='replay': result=replay()
    elif a.command=='audit': result=audit()
    elif a.command=='archive':
        data=read('data/implementation.json.gz')
        if a.name: print(data[a.name]['text'],end='');return
        result={k:{x:v[x]for x in ['original_sha256','sha256','transformation']}for k,v in data.items()}
    else:
        cases=read('data/selected-cases.json.gz')
        if not a.name: result=[{'id':c['id'],'repository':c['repository'],'revision':c['revision']}for c in cases]
        else:
            c=next(c for c in cases if c['id']==a.name)
            result=c if a.part=='all' else c['candidate'] if a.part=='source' else [o['identity']for o in c['observations']] if a.part=='prompt' else [{'kind':o['kind'],'original_answer':o['response'],'parsed_verdict':o['recorded_verdict']}for o in c['observations']]
    print(json.dumps(result,indent=2,sort_keys=True))
if __name__=='__main__': main()
