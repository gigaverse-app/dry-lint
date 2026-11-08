"""Score exact frozen round2 returns; optional independently frozen source labels."""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from data import OUT,ROOT,canonical,digest,read,rows,sha,write
from trace_evaluate import valid_envelope
from dry_lint.judges.command import prompt
from dry_lint.models import Candidate

DEST=OUT/'funded-rounds/round2'
POS={'duplicate','drifted'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-decisions',type=Path,action='append',default=[])
    a=p.parse_args();queue=rows(DEST/'requests.jsonl');side={s['id']:s for s in rows(DEST/'private-sidecar.jsonl')}
    packets={s['id']:s for s in rows(DEST/'review-queue.jsonl')}
    assert sha((DEST/'requests.jsonl').read_bytes())==read(DEST/'VALIDATION.json')['queue_sha256']
    observations=[];run_summaries=[]
    for path in sorted((DEST/'root-run').glob('chunk-*/returned.jsonl')):
        observations+=rows(path)
        run_summaries.append(dict(path=str(path),sha256=sha(path.read_bytes()),summary=read(path.parent/'summary.json')))
    lookup=defaultdict(list)
    for o in observations:lookup[o['request_id']].append(o)
    source={};receipts=[]
    for path in a.source_decisions:
        receipts.append(dict(path=str(path),sha256=sha(path.read_bytes())))
        for r in rows(path):
            if r['id']not in side:continue
            if r['id']in source:raise ValueError('Duplicate independent source decision')
            accepted=r.get('accepted_gold')is True
            bounded=r.get('root_acceptance')=='accepted_bounded_source_assessment'
            classification=r.get('label')
            label=r.get('source_label',classification)
            if accepted and label not in POS|{'separate'}:raise ValueError('Invalid accepted source label')
            if bounded and (r.get('proof_status')!='verified'or not r.get('final_source_review')or label not in POS|{'separate','related'}):
                raise ValueError('Invalid bounded source assessment')
            packet=packets[r['id']]
            if r.get('repository',packet['repository'])!=packet['repository']or r.get('revision',packet['revision'])!=packet['revision']:
                raise ValueError('Independent source pin mismatch')
            # Provider-only flags/confidence never qualify a source label here.
            source[r['id']]=dict(accepted_gold=accepted,accepted_bounded_source_assessment=bounded,
                accepted_for_scoped_scoring=accepted or bounded,label=label,reviewer_classification=classification,
                root_acceptance=r.get('root_acceptance'),decision=r,authority=str(path),authority_sha256=receipts[-1]['sha256'])
    outcomes=[]
    for q in queue:
        verdict,uncertain,error=valid_envelope(q,lookup[q['request_id']])
        outcomes.append(dict(request_id=q['request_id'],id=q['id'],kind=q['kind'],variant=q['variant'],group=q['group'],
            status='unknown'if error else'uncertain'if uncertain else'observed',error=error,uncertain=uncertain,
            verdict=verdict,reported=None if error or uncertain else verdict['label']in POS and verdict['score']>=.8,
            fresh_observations=lookup[q['request_id']],source_status=side[q['id']]['role']))
    # Reuse historical controls exactly, without new calls/costs or contemporary-latency claims.
    for h in rows(DEST/'historical-control-baselines.jsonl'):
        full=Candidate.model_validate(packets[h['id']]['candidate'])
        for kind in('jev','claude'):
            old=h['baseline_'+kind];error=None
            if old['raw_output_sha256']!=digest(old['raw_response']):error='historical raw hash mismatch'
            if not old['exact_current_production_request_match']:error='historical production prompt mismatch'
            if old.get('error')or old.get('validation_error'):error='historical provider/contract error'
            if kind=='jev':
                for s in('new','existing'):
                    if old['actual_body']['state'][s+'_function']['code']!=getattr(full,s).code[:8000]:error='historical body mismatch'
            elif old['identity']['rendered_input']!=prompt(full,policy='shared-operations'):error='historical full prompt mismatch'
            verdict=old['verdict'];uncertain=bool(old.get('uncertain'))
            outcomes.append(dict(id=h['id'],kind=kind,variant=kind+'_baseline',group=side[h['id']]['group'],
                status='unknown'if error or verdict is None else'uncertain'if uncertain else'observed',error=error,uncertain=uncertain,
                verdict=verdict,reported=None if error or verdict is None or uncertain else verdict['label']in POS and verdict['score']>=.8,
                fresh_observations=[],historical_baseline=dict(path=old['path'],observation_file_sha256=old['observation_file_sha256'],
                    output_sha256=old['raw_output_sha256'],original_cost_usd=old['recorded_usd'],new_cost_usd=0,
                    original_seconds=old['seconds'],noncontemporaneous=True),source_status='accepted_source_control'))
    complete_normal=[]
    for kind in('jev','claude'):
        for enriched in(False,True):
            arm=kind+('_body_coverage'if enriched else'_baseline');spent=0
            for caseid,packet in packets.items():
                qs=[q for q in queue if q['id']==caseid and q['variant']==arm]
                if qs:estimate=qs[0]['estimate_usd']
                else:
                    old=next(h for h in rows(DEST/'historical-control-baselines.jsonl')if h['id']==caseid)['baseline_'+kind]
                    text=json.dumps(old['actual_body'],ensure_ascii=True)if kind=='jev'else old['identity']['rendered_input']
                    estimate=(len(text)/2.8*(.04 if kind=='jev'else 2)+(0 if kind=='jev'else 1500))/1e6
                before=spent;admit=spent+estimate<=.04+1e-12
                if admit:spent+=estimate
                complete_normal.append(dict(id=caseid,variant=arm,estimated_usd=estimate,spent_before=before,spent_after=spent,
                    admitted=admit,normal_budget_usd=.04,cache_discount=0,first_loss=None if admit else'normal_estimated_campaign_budget',
                    historical_PR_ledger='unknown',scope='Fixed-order synthetic campaign of all16 cases per arm, including logically charged historical cache controls; not root synthetic intake or an authenticated historical PR.'))
    normal={(r['id'],r['variant']):r for r in complete_normal}
    pairs=[]
    for caseid,s in side.items():
        original_label=s['source_label']if s['accepted_gold']else None
        decision=source.get(caseid);independent=decision['label']if decision and decision['accepted_for_scoped_scoring']else None
        conflict=original_label is not None and decision is not None and (not decision['accepted_for_scoped_scoring']or independent!=original_label)
        label=original_label if original_label is not None else independent
        # Frozen-control analysis stays separate from a potentially conflicting new review.
        for kind in('jev','claude'):
            b=next(o for o in outcomes if o['id']==caseid and o['variant']==kind+'_baseline')
            r=next(o for o in outcomes if o['id']==caseid and o['variant']==kind+'_body_coverage')
            complete=b['reported']is not None and r['reported']is not None
            bp=b['verdict']['label']in POS if b['verdict']else None;rp=r['verdict']['label']in POS if r['verdict']else None
            pairs.append(dict(id=caseid,kind=kind,group=s['group'],role=s['role'],paired_observed=complete,
                source_label=label,frozen_source_label=original_label,independent_source_label=independent,
                source_decision=decision,source_disagreement=conflict,
                baseline_label=b['verdict']['label']if b['verdict']else None,revised_label=r['verdict']['label']if r['verdict']else None,
                baseline_score=b['verdict']['score']if b['verdict']else None,revised_score=r['verdict']['score']if r['verdict']else None,
                baseline_reported=b['reported'],revised_reported=r['reported'],
                recovery=bool(complete and label in POS and r['reported']and not b['reported']),
                lost_positive=bool(complete and label in POS and b['reported']and not r['reported']),
                new_false_report=bool(complete and label=='separate'and r['reported']and not b['reported']),
                binary_positive_gain=bool(complete and label in POS and rp and not bp),
                binary_positive_loss=bool(complete and label in POS and bp and not rp),
                binary_new_false_label=bool(complete and label=='separate'and rp and not bp),
                unscored=label not in POS|{'separate'},baseline_noncontemporaneous=s['accepted_gold'],
                normal_baseline=normal[caseid,kind+'_baseline'],normal_revised=normal[caseid,kind+'_body_coverage'],
                normal_ledger_delta_usd=normal[caseid,kind+'_body_coverage']['estimated_usd']-normal[caseid,kind+'_baseline']['estimated_usd']))
    contrasts={}
    for kind in('jev','claude'):
        for role in('accepted_source_control','novel_unlabelled'):
            selected=[r for r in pairs if r['kind']==kind and r['role']==role]
            contrasts[kind+':'+role]=dict(n=len(selected),paired_observed=sum(r['paired_observed']for r in selected),
                accepted_positives=sum(r['source_label']in POS for r in selected),accepted_separate=sum(r['source_label']=='separate'for r in selected),
                unscored=sum(r['unscored']for r in selected),source_disagreements=sum(r['source_disagreement']for r in selected),
                **{name:sum(r[name]for r in selected)for name in('recovery','lost_positive','new_false_report','binary_positive_gain','binary_positive_loss','binary_new_false_label')})
    arms={}
    for arm in {q['variant']for q in queue}:
        fresh=[o for o in outcomes if o['variant']==arm and o['fresh_observations']]
        physical=[r for o in fresh for r in o['fresh_observations']]
        novel=[o for o in fresh if o['source_status']=='novel_unlabelled']
        arms[arm]=dict(new_calls=len(physical),new_usd=sum(o['physical_cost_usd']or 0 for o in physical),
            sum_api_seconds=sum(o['seconds']for o in physical),mean_api_seconds=statistics.mean(o['seconds']for o in physical)if physical else None,
            mean_novel_api_seconds=statistics.mean(o['fresh_observations'][0]['seconds']for o in novel)if novel else None,
            cached_control_baselines=sum(o['variant']==arm and 'historical_baseline'in o for o in outcomes))
    new_usd=sum(o['physical_cost_usd']or 0 for o in observations)
    independent_contrasts={}
    for kind in('jev','claude'):
        selected=[r for r in pairs if r['kind']==kind]
        qualified=[r for r in selected if r['independent_source_label']in POS|{'separate'}]
        independent_contrasts[kind]=dict(n=len(selected),accepted_positives=sum(r['independent_source_label']in POS for r in qualified),
            accepted_separate=sum(r['independent_source_label']=='separate'for r in qualified),unscored=len(selected)-len(qualified),
            recoveries=sum(r['paired_observed']and r['independent_source_label']in POS and r['revised_reported']and not r['baseline_reported']for r in qualified),
            lost_positives=sum(r['paired_observed']and r['independent_source_label']in POS and r['baseline_reported']and not r['revised_reported']for r in qualified),
            new_false_reports=sum(r['paired_observed']and r['independent_source_label']=='separate'and r['revised_reported']and not r['baseline_reported']for r in qualified),
            removed_false_reports=sum(r['paired_observed']and r['independent_source_label']=='separate'and r['baseline_reported']and not r['revised_reported']for r in qualified),
            note='Independent accepted decisions only; frozen-control analysis remains separately preserved, including disagreements.')
    pending_sources=sum(not(source.get(caseid,{}).get('accepted_for_scoped_scoring')or side[caseid]['accepted_gold'])for caseid in side)
    report=dict(schema=1,status='SOURCE_REVIEW_PENDING'if pending_sources else'FIXED_COMPARISON_SCORED_WITH_NONBINARY_SOURCE_CASES',
        requests=len(queue),returned=len(observations),unknown_answers=sum(o['status']=='unknown'for o in outcomes),
        explicit_uncertain=sum(o['status']=='uncertain'for o in outcomes),actual_new_usd=new_usd,actual_floor_met=new_usd>=.2,
        estimated_new_usd=read(DEST/'HANDOFF.json')['estimated_new_usd'],arms=arms,contrasts=contrasts,root_runs=run_summaries,
        independent_source_comparison=independent_contrasts,
        pending_source_acceptances=pending_sources,
        run_wall_seconds=sum(r['summary']['invocation_wall_seconds']for r in run_summaries),
        actual_concurrency=[r['summary']['concurrency']for r in run_summaries],preparation_default_concurrency=4,
        independent_source_receipts=receipts,model_agreement_is_never_truth=True,retuned_after_check=False,
        unresolved_source_outcomes='Unknown/disputed source decisions are unscored, never negative gold.',
        caveat='Transformed inputs show explicit partial windows, never full native functions. Original full Candidate/model_dump and source remain external immutable evidence. Historical control baselines are noncontemporaneous; fresh novel pairs are analyzed separately.',
        deployment_note='Complete cold normal .04 campaign for all16 cases/arm is named separately. Cache controls retain logical cost; actual PR ledger/first-loss remains unknown.')
    if source:
        from collections import Counter
        report['reviewer_classifications']=dict(Counter(r['reviewer_classification']for r in source.values()))
        report['novel_source_classifications']=dict(Counter(r['reviewer_classification']for caseid,r in source.items()if not side[caseid]['accepted_gold']))
        report['root_acceptance_pending']=sum(not r['accepted_for_scoped_scoring']for r in source.values())
        report['whole_function_gold_promotions']=0
        report['accepted_bounded_source_assessments']=sum(r['accepted_bounded_source_assessment']for r in source.values())
        report['reviewer_proposals_are_not_accepted_gold']=True
        report['reviewer_qualified_positive_effects']={kind:dict(
            proposed_positives=sum(s['label']in POS for s in source.values()),
            baseline_reports=sum(r['baseline_reported']is True for r in pairs if r['kind']==kind and source.get(r['id'],{}).get('label')in POS),
            revised_reports=sum(r['revised_reported']is True for r in pairs if r['kind']==kind and source.get(r['id'],{}).get('label')in POS),
            status='Reviewer-only sensitivity; never substituted for accepted source labels.')for kind in('jev','claude')}
    emit=lambda name,values:(DEST/name).write_text(''.join(canonical(r)+'\n'for r in values))
    join_id=digest(receipts)[:16]if a.source_decisions else None
    suffix='-independent-'+join_id if a.source_decisions else''
    emit('scored-outcomes'+suffix+'.jsonl',outcomes)
    emit('paired-results'+suffix+'.jsonl',pairs)
    emit('normal-funding-complete'+suffix+'.jsonl',complete_normal)
    report['output_paths']={k:str(DEST/(name+suffix+'.jsonl'))for k,name in dict(outcomes='scored-outcomes',pairs='paired-results',normal_ledger='normal-funding-complete').items()}
    name='RESULTS-INDEPENDENT-'+join_id+'.json'if a.source_decisions else'RESULTS-CONTROLS-ONLY.json'
    write('funded-rounds/round2/'+name,report)
    print(canonical({k:report[k]for k in('status','requests','returned','unknown_answers','explicit_uncertain','actual_new_usd','actual_floor_met')}))
    print(canonical(contrasts))


if __name__=='__main__':main()
