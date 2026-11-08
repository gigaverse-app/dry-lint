"""Provider-free selected replay using Python's standard library only.

Recomputes endpoint embedding scores, full recorded-competitor ranks, bounded
operation routing, ordered .04 admissions, canonical answer labels and reports.
No provider call, source execution, model download or credential access.
"""
from pathlib import Path
import gzip, hashlib, json
from collections import Counter

HOME=Path(__file__).resolve().parent
def sha(raw):return hashlib.sha256(raw).hexdigest()
def dot(a,b):return sum(x*y for x,y in zip(a,b,strict=True))
def operation_score(v):
    # Prefix-prefix stays exclusively with the original route.
    values=[dot(a,v['target_prefix']) for a in v['query_operations']]
    values += [dot(v['query_prefix'],b) for b in v['target_operations']]
    values += [dot(a,b) for a in v['query_operations'] for b in v['target_operations']]
    return max(values,default=-1.)
def answer(o):
    if not o['raw_responses']:return None
    raw=o['raw_responses'][-1]['json']
    if o['kind']=='claude':
        text=''.join(part['text'] for part in raw['content'] if part['type']=='text')
        return json.loads(text)
    a=raw['answers'];settings=o['identity']['settings']
    score=float(a['same_concept']['noul']);different=float(a['behaves_differently']['noul'])
    reason=a['reason']['choice']
    rejection=float(a['reason'].get('probabilities',{}).get(reason,0)) if reason!='portable' else 0
    separation=max(float(a['separate_boundary']['noul']),rejection)
    if separation>=.5:score=min(score,1-separation)
    label='separate' if score<settings['drop_below'] else 'drifted' if different>=settings['drift_at'] else 'duplicate'
    return {'label':label,'score':round(score,3)}
def replay_case(case):
    c=case['packet']['candidate'];rep=case['operation_replay'];v=rep['vectors']
    assert abs(dot(v['query_prefix'],v['target_prefix'])-rep['prefix_score'])<2e-6
    assert abs(operation_score(v)-rep['target_operation_score'])<2e-6
    for side,views in [('new',rep['query_views']['views']),('existing',rep['target_views']['views'])]:
        function=c[side]
        for view in views:
            native='\n'.join(function['code'].splitlines()[view['relative_line']-1:view['relative_end_line']])
            assert view['text']==function['name']+'\n'+native
            assert sha(view['text'].encode())==view['input_sha256']
            assert sha(function['code'].encode())==view['function_body_sha256']
            assert view['input_wordpieces']<=256
    for proof,file in zip(case['packet']['source_proofs'],case['source_files'],strict=True):
        raw=(HOME/file['path']).read_bytes();assert sha(raw)==proof['file_sha256']
        function=next(c[side] for side in ['new','existing'] if c[side]['path']==proof['path'] and c[side]['line']==proof['line'])
        assert sha(function['code'].encode())==proof['body_sha256']
        native='\n'.join(raw.decode().splitlines()[proof['line']-1:proof['end_line']])
        assert function['code'].strip() in native.strip()
    scores=rep['competitor_operation_scores'];order=sorted(range(len(scores)),key=lambda i:(-scores[i],i))
    raw=[i for i in order if i!=rep['query_position']]
    rank=raw.index(rep['target_position'])+1
    assert rank==case['ranks']['operation']['raw_nonself']
    winner=next((i for i in order if scores[i]>=.8 and rep['competitor_allowed_after_original'][i]),None)
    assert winner==rep['winner_position']
    before=winner if not rep['original_CPU_returned_candidate'] else None
    after=winner
    answers={o['kind']:answer(o) for o in case['questions_and_answers']}
    for o in case['questions_and_answers']:
        verdict=answers[o['kind']]
        assert verdict['label']==o['recorded_verdict']['label']
        assert abs(verdict['score']-o['recorded_verdict']['score'])<1e-12
    output={'id':case['id'],'role':case['role'],'operation_rank':rank,'prefix_cosine':round(rep['prefix_score'],6),'operation_cosine':round(operation_score(v),6),'v1_operation_target_selected':before==rep['target_position'],'v2_operation_target_selected':after==rep['target_position'],'profiles':{}}
    for profile,rows in case['ledgers'].items():
        arms={}
        for row in rows:arms.setdefault(row['arm'],[]).append(row)
        result={}
        for arm,entries in arms.items():
            spent=0.;selected=False
            for ordinal,row in enumerate(entries,1):
                assert row['ordinal']==ordinal
                candidate=row['candidate']
                eligible=(not candidate['filtered'] and min(candidate[s]['line'] for s in ['new','existing'])>=1
                          and not row['reason'].startswith('route_abstention_guard'))
                funded=eligible and spent+row['normal_charge_usd']<=.04
                if funded:spent+=row['normal_charge_usd']
                assert funded==row['admitted'] and abs(spent-row['cumulative_usd'])<1e-10
                if candidate==c:selected|=funded
            result[arm]={'funded':selected,'reports':{kind:selected and a['label']!='separate' and a['score']>=.8 for kind,a in answers.items()}}
        output['profiles'][profile]=result
    return output

if __name__=='__main__':
    cases=json.loads(gzip.decompress((HOME/'selected-cases.json.gz').read_bytes()))
    results=[replay_case(case) for case in cases]
    allrows=[json.loads(line) for line in (HOME/'all-cases-numeric.jsonl').read_text().splitlines()]
    tables=[]
    for round_number in [1,2]:
        for role in ['candidate','control','rejected_audit']:
            rows=[r for r in allrows if r['round']==round_number and r['role']==role]
            if not rows:continue
            tables.append({'round':round_number,'role':role,'cases':len(rows),'claude_reports':sum(a['label']!='separate' and a['score']>=.8 for r in rows for a in r['answers'] if a['kind']=='claude' and a['label'] is not None),'jev_reports':sum(a['label']!='separate' and a['score']>=.8 for r in rows for a in r['answers'] if a['kind']=='jev' and a['label'] is not None),'source_labels':dict(Counter(r['source_label'] for r in rows)),'new_usd':round(sum(a['new_usd'] or 0 for r in rows for a in r['answers'] if a['newly_paid_here']),8)})
    print(json.dumps({'selected_recomputed':results,'all_cases_numeric_summary':tables,'held_source_recomputed':False,'source_review_is_independent_evidence_not_provider_score':True},indent=2))
