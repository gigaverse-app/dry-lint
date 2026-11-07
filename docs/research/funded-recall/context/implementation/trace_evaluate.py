"""Offline validation/evaluation for the frozen, fresh mixed Jev/Claude source-anchor queue."""
import sys
sys.dont_write_bytecode=True
import argparse
import copy
import json
import math
from collections import defaultdict
from pathlib import Path
from data import OUT,ROOT,canonical,digest,read,rows,sha,write
from experiment import jev_verdict
from dry_lint.judges.command import parse_verdict

DEST=OUT/'trace-derived-v1'
POS={'duplicate','drifted'}


def valid_envelope(q,items):
    if len(items)!=1:return None,None,'missing' if not items else 'duplicate observations'
    o=items[0]
    if o.get('identity')!=q['identity']:return None,None,'identity mismatch'
    if o.get('request_sha256')!=q['identity']['canonical_request_sha256']:return None,None,'request hash mismatch'
    if o.get('sent_wire_sha256')!=q['wire_sha256']:return None,None,'wire hash mismatch'
    raw=o.get('raw_response')
    if not isinstance(raw,dict) or o.get('output_sha256')!=digest(raw):return None,None,'output hash missing/mismatched'
    if o.get('error') or not isinstance(o.get('http_status'),int) or not 200<=o['http_status']<300:return None,None,'provider error'
    if raw.get('model')!=q['model']:return None,None,'returned model mismatch; no fallback authorized'
    if o.get('fresh') is not True:return None,None,'fresh physical call required; cached result not a paired fresh observation'
    if any(isinstance(o.get(k),bool) or not isinstance(o.get(k),(int,float)) or not math.isfinite(o[k]) or o[k]<0
           for k in ('seconds','physical_cost_usd')):return None,None,'missing physical accounting'
    if q['kind']=='jev':return jev_verdict(raw)
    if raw.get('stop_reason') in ('max_tokens','refusal'):return None,None,'truncated/refused Claude output'
    try:
        text=''.join(b['text'] for b in raw['content'] if b.get('type')=='text')
        verdict=parse_verdict(text,'anthropic-operations',q['identity']['version']).model_dump()
        return verdict,False,None
    except (KeyError,TypeError,ValueError):return None,None,'incomplete Claude JSON verdict'


def validate():
    spec=read(DEST/'EXPERIMENT.json');queue=rows(DEST/'requests.jsonl');contexts=rows(DEST/'contexts.jsonl')
    assert spec['facts_sha256']==sha(Path(spec['facts_path']).read_bytes())
    assert spec['questions_sha256']==sha((OUT/'questions.json').read_bytes())
    assert len(queue)==len({q['request_id'] for q in queue})==24
    for q in queue:
        assert q['request_id']==digest(q['identity'])
        assert q['identity']['canonical_request_sha256']==digest(q['request_body'])
        assert q['identity']['source_sha256']==digest(q['source_contract'])
        assert q['identity']['prompt_sha256']==digest(q['prompt_contract'])
        assert sha(q['exact_rendered_json'])==q['wire_sha256']
        assert q['fresh_required'] is True and q['physical_call_policy']['retries']==0
        assert not q['physical_call_policy']['fallbacks']
        original=read(Path(q['full_original_path']))
        for s in ('new','existing'):
            code=original['candidate'][s]['code']
            if q['kind']=='jev':
                sent=q['request_body']['state'][s+'_function']
                assert sent['code']==code[:8000] and sent['code_truncated']==(len(code)>8000)
                assert q['request_body']['questions']==read(OUT/'questions.json')['baseline']
            else:assert code in q['request_body']['messages'][0]['content']
    assert sum(q['reservation_usd'] for q in queue)<=spec['budget']['root_remaining_shared_teacher_context_usd']
    assert len({q['group'] for q in queue})==6
    assert not {q['group'] for q in queue}.intersection(spec['learning_groups'])
    for c in contexts:
        for s in ('new','existing'):assert len(c['sides'][s]['text'])<=4000
    # In-memory synthetic envelopes exercise both output contracts; they are never saved as observations.
    js=next(q for q in queue if q['kind']=='jev')
    original=next(r for r in rows(OUT/'audit.jsonl') if r['id']==js['id'])
    for q,raw in [(js,original['jev']['raw_response']),
                  (next(q for q in queue if q['kind']=='claude'),
                   dict(model='claude-sonnet-5-5',stop_reason='end_turn',content=[dict(type='text',text='{"label":"separate","score":0.1,"owner":"","why":"Synthetic parser invariant only."}')]))]:
        record=dict(identity=q['identity'],request_sha256=q['identity']['canonical_request_sha256'],
            sent_wire_sha256=q['wire_sha256'],raw_response=raw,output_sha256=digest(raw),
            http_status=200,error=None,fresh=True,seconds=.1,physical_cost_usd=.001)
        assert valid_envelope(q,[record])[2] is None
        assert valid_envelope(q,[])[2]=='missing'
        altered=copy.deepcopy(record);altered['fresh']=False
        assert valid_envelope(q,[altered])[2] is not None
        altered=copy.deepcopy(record);altered['output_sha256']='bad'
        assert valid_envelope(q,[altered])[2] is not None
    result=dict(schema=1,all_pass=True,requests=24,cases=6,
                queue_sha256=sha((DEST/'requests.jsonl').read_bytes()),
                recipe_sha256=sha((DEST/'EXPERIMENT.json').read_bytes()),
                fresh_cache_stale_output_and_missing_contract_checks=True,provider_calls=0,
                no_teacher_check_traces_or_verdicts_read=True)
    write('trace-derived-v1/validation.json',result)
    # Normal logical campaign projections are separate from the offline research request queue.
    projection=[]
    for arm in spec['arms']:
        spent=0.
        for q in queue:
            if q['variant']!=arm:continue
            funded=spent+q['estimate_usd']<=.04+1e-12
            before=spent
            if funded:spent+=q['estimate_usd']
            projection.append(dict(id=q['id'],variant=arm,normal_estimated_usd=q['estimate_usd'],
                spent_before=before,spent_after=spent,normal_campaign_budget_usd=.04,normal_funded=funded,
                first_loss=None if funded else 'normal_estimated_campaign_budget',
                note='Synthetic fixed-order cold campaign, not a real historical PR diff/ledger. Budget denial is not a source label.'))
    (DEST/'normal-budget-projection.jsonl').write_text(''.join(canonical(p)+'\n' for p in projection))
    return result


def evaluate(observations):
    validate();queue=rows(DEST/'requests.jsonl');caseinfo={r['id']:r for r in read(DEST/'cases.json')}
    returned=rows(observations) if observations else []
    byid=defaultdict(list)
    for o in returned:byid[o.get('request_id')].append(o)
    outcomes=[]
    for q in queue:
        v,uncertain,error=valid_envelope(q,byid[q['request_id']])
        outcomes.append(dict(request_id=q['request_id'],id=q['id'],variant=q['variant'],kind=q['kind'],
            role=q['split'],group=q['group'],verdict=v,uncertain=uncertain,
            status='unknown' if error else 'uncertain' if uncertain else 'observed',error=error,
            reported=None if error or uncertain else v['label'] in POS and v['score']>=.8,
            source=caseinfo[q['id']],raw_observations=byid[q['request_id']],
            normal_estimate_usd=q['estimate_usd'],normal_ledger_delta_usd=q['normal_ledger_delta_usd']))
    (DEST/'outcomes.jsonl').write_text(''.join(canonical(o)+'\n' for o in outcomes))
    contrasts={}
    for kind in ('jev','claude'):
        pairs=[]
        for caseid,source in caseinfo.items():
            arms={o['variant']:o for o in outcomes if o['id']==caseid}
            a,b=arms[kind+'_source_anchors'],arms[kind+'_baseline']
            complete=a['reported'] is not None and b['reported'] is not None
            label=source['source_label'] if source['accepted_gold'] else None
            pairs.append(dict(id=caseid,role=source['role'],source_label=label,paired_observed=complete,
                recovery=bool(complete and label in POS and a['reported'] and not b['reported']),
                lost_positive=bool(complete and label in POS and b['reported'] and not a['reported']),
                new_false_report=bool(complete and label=='separate' and a['reported'] and not b['reported']),
                unscored_source=label not in POS|{'separate'},
                normal_ledger_delta_usd=a['normal_ledger_delta_usd']))
        contrasts[kind]=dict(rows=pairs,recoveries=sum(r['recovery'] for r in pairs),
            lost_positives=sum(r['lost_positive'] for r in pairs),new_false_reports=sum(r['new_false_report'] for r in pairs),
            paired_observed=sum(r['paired_observed'] for r in pairs))
    report=dict(schema=1,status='pending_returned_observations' if any(o['status']=='unknown' for o in outcomes) else 'observed_development_comparison',
        requests=len(queue),returned=len(returned),unknown=sum(o['status']=='unknown' for o in outcomes),
        explicit_uncertain=sum(o['status']=='uncertain' for o in outcomes),within_model_context_effects=contrasts,
        all_returned_physical_usd=sum(o.get('physical_cost_usd',0) or 0 for o in returned),
        unjoined_observations=[o for o in returned if o.get('request_id') not in {q['request_id'] for q in queue}],
        model_agreement_is_never_truth=True,
        limitation='Source-scoped development labels; only one shot per arm. Jev truncates body at 8000 while Claude '
                   'keeps full bodies. No cross-model score equivalence, pristine holdout, or automatic production promotion. '
                   'Normal synthetic .04 campaign projections live separately in normal-budget-projection.jsonl.',
        original72='Unchanged fixed-method result remains in ../pilot-results.json; this recipe used only supplied learning facts.')
    write('trace-derived-v1/evaluation.json',report)
    print(canonical({k:report[k] for k in ('status','requests','returned','unknown','explicit_uncertain')}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--observations',type=Path);p.add_argument('--validate-only',action='store_true')
    args=p.parse_args()
    print(canonical(validate())) if args.validate_only else evaluate(args.observations)
