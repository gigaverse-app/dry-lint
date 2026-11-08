"""Pinned, deterministic body-coverage experiment; provider-free preparation."""
import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path
from data import OUT,ROOT,canonical,digest,read,rows,sha,write
from extract_context import Source
from dry_lint.models import Candidate
from dry_lint.judges.jev import state
from dry_lint.judges.command import prompt
from dry_lint.bench_background import BenchBackground
from dry_lint.functions import selected_path

DEST=OUT/'funded-rounds/round2'
ARMS=['jev_baseline','jev_body_coverage','claude_baseline','claude_body_coverage']


def emit(name, values):
    p=DEST/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(''.join(canonical(x)+'\n'for x in values))


def windows(code, first_line):
    if len(code)<=8000:
        return dict(code=code,complete=True,original_sha256=sha(code),rendered_sha256=sha(code),segments=[dict(
            original_start_char=0,original_end_char_exclusive=len(code),original_start_line=first_line,
            original_end_line=first_line+code.count('\n'),rendered_start_char=0,rendered_end_char_exclusive=len(code))])
    chunks=[];mapping=[];used=[];rendered=''
    for fraction in (0,1/3,2/3,1):
        raw_start=round((len(code)-1600)*fraction)
        start=code.rfind('\n',0,raw_start)+1
        # Avoid crossing a distant preceding line on minified input.
        if raw_start-start>200:start=raw_start
        limit=min(len(code),start+1600)
        end=code.rfind('\n',start,limit)
        if end<=start:end=limit
        if fraction==1:
            end=len(code);start=max(0,end-1600)
            n=code.find('\n',start,end)
            if 0<=n<start+200:start=n+1
        if any(max(start,a)<min(end,b)for a,b in used):
            raise ValueError('overlapping_coverage_windows')
        used.append((start,end))
        marker='\n/* PARTIAL SOURCE WINDOW chars '+str(start)+':'+str(end)+' of '+str(len(code))+'; intervening code omitted */\n'
        rendered+=marker;offset=len(rendered);rendered+=code[start:end]
        mapping.append(dict(original_start_char=start,original_end_char_exclusive=end,
            original_start_line=first_line+code[:start].count('\n'),original_end_line=first_line+code[:end].count('\n'),
            original_start_column=start-(code.rfind('\n',0,start)+1),
            rendered_start_char=offset,rendered_end_char_exclusive=len(rendered),segment_sha256=sha(code[start:end])))
    assert len(rendered)<=7200
    return dict(code=rendered,complete=False,original_sha256=sha(code),rendered_sha256=sha(rendered),segments=mapping,
        omission='Partial disjoint source excerpts, never a full native function; missing intervals remain unknown.')


def endpoint(r, f):
    return(r['repository'],r['revision'],f['path']+'::'+((f['owner']+'.')if f.get('owner')else '')+f['name'])


def freeze():
    DEST.mkdir(parents=True,exist_ok=True)
    p=DEST/'EXPERIMENT.json'
    assert not p.exists(),'Already preregistered; no silent refreeze'
    spec=dict(schema=1,experiment='jev-context-body-coverage-round2-v1',mechanism='body-coverage-v1',
        rationale='Round1 imports/preceding/prefix anchors produced zero .8 recoveries; they leave the body-prefix visibility deficit intact. Earlier verified source operations include regions beyond Jev8000. Test source coverage separately from helper reasoning; no gold regions guide extraction.',
        windows=dict(native_short_limit=8000,anchors=[0,1/3,2/3,1],chars_per_window=1600,
            line_alignment_slack=200,rendered_limit=7200,context_recipe='No source anchors or added semantic rationale; preserve native original source_context unchanged.',
            mapping='Exact character offsets, source lines, segment hashes, original/rendered body SHA; explicit partial-source markers.'),
        questions='Frozen context-v3 Jev questions and shared-operations Claude question; unchanged from round1.',
        arms=ARMS,novel_pair_limit=12,controls=dict(positives=2,separate=2,baseline='Reuse exact historical recorded baselines only; no paid repeats. Record noncontemporaneous comparison separately.'),
        selection='Use only own cached retained TF-IDF inventory. Union every retained source endpoint and known source-family lineage before selection. Exclude components intersecting round1 or teacher learning. Novel components also exclude historical judged endpoints. One pair per connected component, at least one native body >8000 chars, combined bodies <=100000 chars. Sort by stable source-key hash; no output-driven replacement.',
        expected_new_spend_target_usd=[.25,.35],required_actual_new_usd=.20,root_context_reserve_usd=2,
        spending='Root-only; new actual usage once, caches excluded, no repeats to fill quota. Root stops/adapts after chunk receipts; overall20 authorization. Keep old ledger entries. Normal .04 ledger separate.',
        chunk_size=32,disjointness='Entire endpoint/known-family connected components; interval overlap and same-name lineage verified for selected native endpoints before freezing queue.',
        scoring=dict(threshold=.8,truth='Independent source-accepted partial-operation labels only. Novel labels unknown until independent review; never infer truth from model agreement.',
            outcomes=['recoveries','lost_positive_reports','new_false_reports','binary_label_effects','unknown','fresh_usd','cached_usd','latency'],
            promote='Source-supported positive net recoveries with no new separate reports or lost positives on controls; unknown novel labels cannot establish benefit. No threshold tuning.'),
        errors_used='Aggregate round1 failures plus previously verified clipping deficit, no round2 outcomes. Teacher-v2 invalid traces unused.',
        recipe_source_sha256=sha(Path(__file__).read_bytes()),round1_queue_sha256=sha((OUT/'trace-derived-v1/requests.jsonl').read_bytes()),
        questions_sha256=sha((OUT/'questions.json').read_bytes()),provider_calls_by_worker=0)
    p.write_text(json.dumps(spec,indent=2,sort_keys=True)+'\n')
    print(canonical(dict(status='PREREGISTERED',spec_sha256=sha(p.read_bytes()))))


def prepare():
    spec=read(DEST/'EXPERIMENT.json');assert spec['recipe_source_sha256']==sha(Path(__file__).read_bytes())
    assert not(DEST/'HANDOFF.json').exists(),'Prepared queue immutable; do not silently replace'
    source=Source();pool=rows(OUT/'full-corpus/novel-candidate-inventory.jsonl');audit=rows(OUT/'audit.jsonl')
    parent={}
    def find(x):
        parent.setdefault(x,x)
        if parent[x]!=x:parent[x]=find(parent[x])
        return parent[x]
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    for r in pool:
        if not r['exclusion']:union(*[(r['repository'],r['revision'],v)for v in r['source_pair']])
    byid={r['id']:r for r in audit}
    for group in read(OUT/'groups.json'):
        es=[endpoint(byid[i],byid[i]['candidate'][s])for i in group['members']if i in byid for s in ('new','existing')]
        for e in es[1:]:union(es[0],e)
    blocked_ids={r['id']for r in read(OUT/'trace-derived-v1/cases.json')}|{r['id']for r in read(OUT/'trace-derived-v1/learning-observation-summary.json')['cases']}
    blocked={find(endpoint(byid[i],byid[i]['candidate'][s]))for i in blocked_ids for s in ('new','existing')}
    observed={find(endpoint(r,r['candidate'][s]))for r in audit for s in ('new','existing')}
    # Sealed-intake novel pair calls also stay outside this round.
    old_feed=ROOT/'reports/research-experiments/intake-seven/jev-context-provider-feed.jsonl'
    for r in rows(old_feed):
        for s in ('new','existing'):observed.add(find(endpoint(r['packet'],r['packet']['candidate'][s])))
    bgcache={}
    def bg(repo):
        if repo not in bgcache:
            proof=source.repositories[repo]['background_proof'];raw=Path(proof['path']).read_bytes()
            assert sha(raw)==proof['sha256'];b=BenchBackground.decode(raw)
            docs=defaultdict(list)
            for d in b.documents:docs[d.id].append(d)
            bgcache[repo]=(b,docs,proof)
        return bgcache[repo]
    def packet(item):
        repo,pin=item['repository'],item['revision'];b,docs,proof=bg(repo);fs=[]
        for name in item['source_pair']:
            path=name.split('::')[0];assert selected_path(path,b.scope['include'],b.scope['exclude'])
            matches=[f for f in source.functions(repo,pin,path)if f.qualname==name]
            assert len(matches)==1,'Ambiguous/missing native symbol'
            f=matches[0];ds=[d for d in docs[name]if d.source_sha256==sha(f.code)]
            assert len(ds)==1,'Ambiguous/missing exact native background row'
            fs.append(f)
        lengths=[len(f.code)for f in fs]
        if max(lengths)<=8000 or sum(lengths)>100000:return None
        c=Candidate(new=fs[0],existing=fs[1],similarity=item['sampling_score'],comparer='tfidf:2',lane='exploration')
        p=dict(schema=1,format='dry-lint/lab-review-packet',id='JCTX-R2-'+digest([repo,pin,item['source_pair']])[:16],
            repository=repo,revision=pin,candidate=c.model_dump(),background_proof=proof,source_status='unknown',accepted_gold=False)
        p['source_proofs']=[source.verify_endpoint(p,s)for s in ('new','existing')]
        return p
    controls=[];used=set();failures=[]
    for label in ('duplicate','separate'):
        candidates=[r for r in audit if r['accepted_gold']and r['source_label']==label and max(len(r['candidate'][s]['code'])for s in ('new','existing'))>8000 and sum(len(r['candidate'][s]['code'])for s in ('new','existing'))<=100000]
        for r in sorted(candidates,key=lambda r:digest([r['repository'],r['revision'],r['id']])):
            components={find(endpoint(r,r['candidate'][s]))for s in ('new','existing')}
            if components&(blocked|used):continue
            c=Candidate.model_validate(r['candidate']);proof=source.repositories[r['repository']]['background_proof']
            p=dict(schema=1,format='dry-lint/lab-review-packet',id=r['id'],repository=r['repository'],revision=r['revision'],
                candidate=c.model_dump(),background_proof=proof,source_status='accepted_partial_operation_control',accepted_gold=True)
            p['source_proofs']=[source.verify_endpoint(p,s)for s in ('new','existing')]
            controls.append((p,r));used|=components
            if sum(t[1]['source_label']==label for t in controls)==2:break
    candidates=[r for r in pool if not r['exclusion']and r['sampling_score']is not None and find((r['repository'],r['revision'],r['source_pair'][0]))not in blocked|observed]
    candidates.sort(key=lambda r:digest([r['repository'],r['revision'],r['source_pair']]))
    novel=[];scanned=0
    for item in candidates:
        component=find((item['repository'],item['revision'],item['source_pair'][0]))
        if component in used:continue
        scanned+=1
        try:p=packet(item)
        except (ValueError,AssertionError,KeyError)as exc:
            failures.append(dict(pair=item['source_pair'],status=type(exc).__name__));continue
        if p is None:continue
        novel.append((p,item));used.add(component)
        if len(novel)==spec['novel_pair_limit']:break
    assert len(novel)>=6 and len(controls)==4,'Insufficient eligible supply; retain receipt, root verifies'
    questions=read(OUT/'questions.json')['baseline'];requests=[];contexts=[];sidecars=[];originals=[];history=[]
    all_packets=[p for p,_ in controls+novel]
    for p,info in controls+novel:
        iscontrol=p['accepted_gold'];c=Candidate.model_validate(p['candidate'])
        coverage={s:windows(getattr(c,s).code,getattr(c,s).line)for s in ('new','existing')}
        revised={s:coverage[s]['code']for s in ('new','existing')}
        full=dict(p,candidate_model_dump=c.model_dump());op=DEST/'originals'/(p['id']+'.json');op.parent.mkdir(exist_ok=True);op.write_text(canonical(full)+'\n')
        base_jev=info['jev']['actual_body']if iscontrol else dict(model='jev-1.14.0',state=state(c,True),questions=questions)
        base_claude=prompt(c,policy='shared-operations')
        edits=[]
        for s in ('new','existing'):
            code=getattr(c,s).code
            if coverage[s]['complete']:continue
            assert base_claude.count(code)==1,'Cannot unambiguously transform native Claude rendering'
            start=base_claude.index(code);edits.append((start,start+len(code),revised[s]))
        transformed_claude=base_claude
        for start,end,value in sorted(edits,reverse=True):transformed_claude=transformed_claude[:start]+value+transformed_claude[end:]
        group=digest(sorted(str(find(endpoint(p,p['candidate'][s])))for s in ('new','existing')))
        sidecars.append(dict(id=p['id'],role='accepted_source_control'if iscontrol else'novel_unlabelled',group=group,
            source_label=info['source_label']if iscontrol else None,accepted_gold=iscontrol,
            selection=info if not iscontrol else dict(source_review=info['source_review'],source_label=info['source_label']),
            normal_funding_status='Native retrieval unchanged; root authentic PR ledger absent. Diagnostic allocation is separate.',
            family='retained endpoint + known source-family connected component'))
        contexts.append(dict(id=p['id'],coverage=coverage,group=group))
        if iscontrol:
            history.append(dict(id=p['id'],baseline_jev=info['jev'],baseline_claude=info['claude'],
                accepted_gold=True,source_label=info['source_label'],status='Historical exact baseline, not new spend or contemporary latency. Preserve negatives/uncertainty.'))
        for kind in ('jev','claude'):
            for variant in (kind+'_baseline',kind+'_body_coverage'):
                if iscontrol and variant.endswith('baseline'):continue
                enriched=variant.endswith('body_coverage');model='jev-1.14.0'if kind=='jev'else'claude-sonnet-5-5';cap=None if kind=='jev'else 1024;rates=[.04,0]if kind=='jev'else[2.,10.]
                if kind=='jev':
                    body=copy.deepcopy(base_jev)
                    if enriched:
                        for s in ('new','existing'):
                            body['state'][s+'_function']['code']=revised[s]
                            body['state'][s+'_function']['code_truncated']=not coverage[s]['complete']
                else:body=dict(model=model,max_tokens=cap,messages=[dict(role='user',content=transformed_claude if enriched else base_claude)])
                sc=dict(repository=p['repository'],revision=p['revision'],endpoints=p['source_proofs'],candidate_model_dump_sha256=digest(p['candidate']),
                    recipe_sha256=sha((DEST/'EXPERIMENT.json').read_bytes()),body_transform_sha256=digest(coverage)if enriched else None)
                pc=dict(request=body,model=model,version=spec['experiment']+':'+variant,output_cap=cap,tools=False,retries=0,fallbacks=False)
                identity=dict(source_sha256=digest(sc),prompt_sha256=digest(pc),canonical_request_sha256=digest(body),model=model,version=pc['version'],output_cap=cap)
                wire=canonical(body);text=json.dumps(body,ensure_ascii=True)if kind=='jev'else body['messages'][0]['content']
                estimate=(len(text)/2.8*rates[0]+(150 if kind=='claude'else 0)*rates[1])/1e6
                requests.append(dict(schema=1,experiment=spec['experiment'],id=p['id'],variant=variant,kind=kind,request_id=digest(identity),identity=identity,
                    source_contract=sc,prompt_contract=pc,method='POST',url='https://api.typesafe.ai/v1/systemone'if kind=='jev'else'https://api.anthropic.com/v1/messages',
                    request_body=body,exact_rendered_json=wire,wire_sha256=sha(wire),model=model,model_version=pc['version'],max_output_tokens=cap,
                    estimate_usd=estimate,reservation_usd=((len(wire.encode())+1024)*rates[0]+(cap or 0)*rates[1])/1e6,
                    reservation_rates_per_million=rates,normal_budget_usd=.04,normal_ledger_rendered_input=text,normal_ledger_input_sha256=sha(text),
                    fresh_required=True,physical_call_policy=dict(concurrency=4,retries=0,max_attempts=1,fallbacks=False),
                    split='control_historical_baseline'if iscontrol else'novel_source_review_pending',group=group,full_original_path=str(op),
                    body_transform=dict(version='body-coverage-v1'if enriched else'native-production-rendering',coverage=coverage if enriched else None),
                    source_status='Accepted scoped control'if iscontrol else'Unknown; provider agreement is not truth'))
    emit('review-queue.jsonl',all_packets);emit('private-sidecar.jsonl',sidecars);emit('contexts.jsonl',contexts);emit('historical-control-baselines.jsonl',history)
    emit('source-manifest.jsonl',source.receipts);emit('failures.jsonl',failures);emit('requests.jsonl',requests)
    emit('source-blind.jsonl',[dict(id=p['id'],repository=p['repository'],revision=p['revision'],candidate=p['candidate'],source_proofs=p['source_proofs'])for p,_ in novel])
    chunks=[]
    for offset in range(0,len(requests),32):
        name='chunks/chunk-'+str(offset//32+1).zfill(2)+'.jsonl';block=requests[offset:offset+32];emit(name,block)
        chunks.append(dict(path=str(DEST/name),sha256=sha((DEST/name).read_bytes()),requests=len(block),estimated_new_usd=sum(q['estimate_usd']for q in block),reservation_usd=sum(q['reservation_usd']for q in block)))
    normal=[]
    for arm in ARMS:
        spent=0
        for q in requests:
            if q['variant']!=arm:continue
            admit=spent+q['estimate_usd']<=.04+1e-12;before=spent
            if admit:spent+=q['estimate_usd']
            normal.append(dict(id=q['id'],variant=arm,estimate_usd=q['estimate_usd'],spent_before=before,spent_after=spent,
                admitted=admit,normal_cap_usd=.04,first_loss=None if admit else'normal_estimated_campaign_budget',
                historical_PR_funding='unknown',note='Fixed-order synthetic cold campaign; no cache discount; diagnostic funding separate.'))
    emit('normal-funding.jsonl',normal)
    handoff=dict(schema=1,direction='jev-context',round=2,status='PREPARED_VALIDATION_REQUIRED',mechanism='body-coverage-v1',
        queue=str(DEST/'requests.jsonl'),manifest=str(DEST/'review-queue.jsonl'),sourceproof=str(DEST/'source-manifest.jsonl'),funding=str(DEST/'normal-funding.jsonl'),
        private_sidecar=str(DEST/'private-sidecar.jsonl'),source_blind=str(DEST/'source-blind.jsonl'),chunks=chunks,
        requests=len(requests),novel_pairs=len(novel),accepted_controls=len(controls),eligible_cached_metadata_pairs=len(candidates),source_pairs_scanned=scanned,
        estimated_new_usd=sum(q['estimate_usd']for q in requests),minimum_actual_new_usd=.2,worker_provider_calls=0,vector_refits=0,
        baseline_reuse='Controls use historical exact answers separately, no new baseline calls. All novel baseline/revised requests are fresh scientific pairs.',
        root_budget='Use ROOT-authorized shared-budget v2 (cap2) retaining ALL existing entries; never reset or initialize from zero. Root central executes and sources independent review.',
        central_intake_schema='review-queue.jsonl uses existing dry-lint/lab-review-packet schema. requests.jsonl uses frozen mixed exact-payload contract from validated root24. The original intake-seven six-arm renderer does not support this four-arm transform; use exact transport, not production re-rendering.',
        next='Validate native/background proofs and line maps. Execute chunk01 first, then next chunk only as root actual new round2 spending requires; no paid repeats or cache spend credit.')
    write('funded-rounds/round2/HANDOFF.json',handoff)
    print(canonical({k:handoff[k]for k in ('status','requests','novel_pairs','accepted_controls','source_pairs_scanned','estimated_new_usd')}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['freeze','prepare']);a=p.parse_args()
    freeze()if a.command=='freeze'else prepare()
