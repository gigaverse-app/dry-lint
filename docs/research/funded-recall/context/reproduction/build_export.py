"""Export frozen study artifacts. Local files/Git objects only; never import lab runners."""
import argparse
import ast
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

def canonical(x):
    return json.dumps(x,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)
def sha(x):
    return hashlib.sha256(x if isinstance(x,bytes) else x.encode()).hexdigest()
def rows(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def read(p):
    return json.loads(p.read_text())
def blob(repo,pin,path):
    return subprocess.check_output(['git','--no-replace-objects','-C',str(repo),'cat-file','blob',pin+':'+path])
def dump(p,obj):
    raw=(canonical(obj)+'\n').encode()
    p.write_bytes(gzip.compress(raw,mtime=0) if p.suffix=='.gz' else raw)
def clean(x,root):
    if isinstance(x,dict):
        return {k:clean(v,root) for k,v in x.items()}
    if isinstance(x,list):
        return [clean(v,root) for v in x]
    if isinstance(x,str):
        return x.replace(str(root)+'/', 'lab-archive:/')
    return x
def response(raw,held=False):
    # Explicit allowlist: no IDs, headers, diagnostics, thinking/reasoning blocks.
    result={k:raw[k] for k in ('model','stop_reason') if k in raw}
    result['usage']={k:v for k,v in raw['usage'].items()
                     if k in ('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')}
    if 'answers' in raw:
        result['answers']=raw['answers']
    else:
        blocks=[b for b in raw['content'] if b.get('type')=='text']
        if held:
            obj=json.loads(''.join(b['text'] for b in blocks))
            obj={k:obj[k] for k in ('label','score','owner') if k in obj}
            result['content']=[dict(type='text',text=canonical(obj))]
            result['source_text_withheld']=True
        else:
            result['content']=[dict(type='text',text=b['text']) for b in blocks]
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--lab-root',required=True,type=Path)
    a=ap.parse_args();root=a.lab_root;dest=Path(__file__).resolve().parent
    work=root/'jobs/experiment-jev-context';base=work/'.lab-results'
    rounds={'R1':base/'trace-derived-v1','R2':base/'funded-rounds/round2'}
    repositories=read(root/'jobs/review-automation/.lab-results/review-automation/repositories-five.json')
    bindings={r['repository']:r for r in repositories}
    held_id='KZ-12db7f631134d1ce'
    evidence=dict(schema=1,requests=[],observations=[],cases=[],contexts={},specifications={},
                  source_decisions={},runs=[],withheld=[],artifact_provenance=[])
    def provenance(path):
        evidence['artifact_provenance'].append(dict(path=str(path.relative_to(root)),sha256=sha(path.read_bytes())))
    final=rounds['R2']/'paired-results-independent-75ffc2e13f95a823.jsonl'
    evidence['expected_R2_pairs']=clean(rows(final),root);provenance(final)
    scored=rounds['R2']/'scored-outcomes-independent-75ffc2e13f95a823.jsonl'
    evidence['expected_verdicts']=[]
    for tag,path in [('R1',rounds['R1']/'outcomes.jsonl'),('R2',scored)]:
        provenance(path)
        for o in rows(path):
            v=o['verdict']
            if o['id']==held_id and o['kind']=='claude':
                v={k:v[k] for k in ('label','score','owner')}
            evidence['expected_verdicts'].append(dict(round=tag,id=o['id'],variant=o['variant'],
                                                       verdict=v,uncertain=o['uncertain'],reported=o['reported']))
    source_paths=[root/'reports/research-experiments/promotion/context-round2-source/coordinator-decisions.jsonl',
                  rounds['R2']/'existing-accepted-source-controls.jsonl']
    for p in source_paths:
        provenance(p)
        evidence['source_decisions'][p.name]=clean(rows(p),root)
    public_files={};source_index={};trees={}
    extraction={}
    for p in (base/'extraction-cache').glob('*.json'):
        cached=read(p);identity=cached['identity']
        for f in cached['functions']:
            native={k:v for k,v in f.items() if k not in ('tokens','calls')}
            extraction[(identity['repository'],identity['revision'],f['path'],f['line'],sha(f['code']))]=(native,identity['contract'])
    for r in repositories:
        if r['repository']=='Garsson-io/kaizen':continue
        trees[r['repository']]=subprocess.check_output(['git','--no-replace-objects','-C',r['git'],'ls-tree','-r','--name-only',r['revision']]).decode().splitlines()
    for tag,rd in rounds.items():
        spec=read(rd/'EXPERIMENT.json');provenance(rd/'EXPERIMENT.json')
        evidence['specifications'][tag]=clean(spec,root)
        context=rows(rd/'contexts.jsonl')
        evidence['contexts'][tag]=[x for x in context if x['id']!=held_id]
        for p in sorted((rd/'originals').glob('*.json')):
            original=read(p);cid=original['id'];provenance(p)
            case=dict(round=tag,id=cid,repository=original['repository'],revision=original['revision'],
                      candidate_sha256=sha(canonical(original['candidate'])),
                      candidate_model_dump_sha256=sha(canonical(original['candidate_model_dump'])))
            proofs=original.get('source_checks',original.get('source_proofs'))
            case['source_proofs']=proofs
            case['native_extraction_proofs']={}
            for side in ('new','existing'):
                f=original['candidate'][side]
                cached=extraction.get((case['repository'],case['revision'],f['path'],f['line'],sha(f['code'])))
                if cached:
                    native,contract=cached
                    case['native_extraction_proofs'][side]=dict(native_model_dump_sha256=sha(canonical(native)),
                        candidate_fields_differing_from_native=[k for k in f if f[k]!=native.get(k)],contract=contract)
                else:
                    case['native_extraction_proofs'][side]=dict(status='No cached native object; compare frozen body, coordinates and structure hash directly. Historical context is preserved separately.')
            if cid==held_id:
                c=original['candidate']
                case['candidate_shell']={k:v for k,v in c.items() if k not in ('new','existing')}
                case['endpoints']={s:{k:c[s][k] for k in ('path','name','owner','line','end_line')} for s in ('new','existing')}
                case['function_sha256']={s:sha(canonical(c[s])) for s in ('new','existing')}
                case['withheld']='Redistribution held; source-bearing fields require user-run hydration.'
            else:
                case['candidate']=original['candidate'];case['candidate_model_dump']=original['candidate_model_dump']
            if tag=='R1':
                case['assessment']=next(x for x in read(rd/'cases.json') if x['id']==cid)
            else:
                paired=next(x for x in evidence['expected_R2_pairs'] if x['id']==cid)
                case['assessment']={k:paired[k] for k in ('source_label','role','group','independent_source_label')}
            evidence['cases'].append(case)
        provenance(rd/'requests.jsonl')
        for q in rows(rd/'requests.jsonl'):
            keep=['id','variant','kind','request_id','identity','source_contract','prompt_contract','method','url',
                  'request_body','exact_rendered_json','wire_sha256','model','max_output_tokens','estimate_usd',
                  'reservation_usd','reservation_rates_per_million','group','split','physical_call_policy',
                  'normal_ledger_input_sha256']
            item={k:q[k] for k in keep};item.update(round=tag,historical=False)
            if q['id']==held_id:
                for k in ('request_body','exact_rendered_json','prompt_contract'):item.pop(k)
                item['withheld']=True
            evidence['requests'].append(item)
        paths=sorted((rd/'root-run').glob('chunk-*/returned.jsonl')) if tag=='R2' else [rd/'root-run/returned.jsonl']
        for p in paths:
            provenance(p)
            summary=read(p.parent/'summary.json')
            evidence['runs'].append(dict(round=tag,concurrency=summary['concurrency'],wall_seconds=summary['invocation_wall_seconds']))
            for o in rows(p):
                q=next(x for x in evidence['requests'] if x['request_id']==o['request_id'])
                obj={k:o[k] for k in ('request_id','identity','request_sha256','sent_wire_sha256','http_status','error','fresh','seconds','physical_cost_usd')}
                obj['original_raw_response_sha256']=o['output_sha256']
                obj['response']=response(o['raw_response'],q['id']==held_id)
                obj['sanitized_response_sha256']=sha(canonical(obj['response']))
                evidence['observations'].append(obj)
        # File content belongs to pinned licensed public repositories only.
        for entry in rows(rd/'source-manifest.jsonl'):
            if entry['repository']=='Garsson-io/kaizen':continue
            r=bindings[entry['repository']];raw=blob(r['git'],entry['revision'],entry['path'])
            assert sha(raw)==entry['file_sha256']
            key=entry['file_sha256']
            source_index[canonical([entry['repository'],entry['revision'],entry['path']])]=key
            public_files[key]=dict(repository=entry['repository'],revision=entry['revision'],path=entry['path'],
                                   sha256=key,text=raw.decode())
    history=rounds['R2']/'historical-control-baselines.jsonl';provenance(history)
    for h in rows(history):
        for kind in ('jev','claude'):
            old=h['baseline_'+kind]
            body=old['actual_body'] if kind=='jev' else dict(model='claude-sonnet-5-5',max_tokens=1024,
                messages=[dict(role='user',content=old['identity']['rendered_input'])])
            wire=canonical(body)
            rid='historical:'+h['id']+':'+kind
            q=dict(round='R2',id=h['id'],kind=kind,variant=kind+'_baseline',request_id=rid,historical=True,
                   request_body=body,exact_rendered_json=wire,wire_sha256=sha(wire),model=body['model'],
                   method='POST',url='https://api.typesafe.ai/v1/systemone' if kind=='jev' else 'https://api.anthropic.com/v1/messages',
                   max_output_tokens=None if kind=='jev' else 1024,reservation_rates_per_million=[.04,0]if kind=='jev' else[2,10],
                   historical_identity=old['identity'],historical_prompt_sha256=old.get('prompt_canonical_sha256'),
                   wire_provenance='Canonical playback reconstructed from recorded body/rendered input; original wire bytes not retained.')
            q['reservation_usd']=((len(wire.encode())+1024)*q['reservation_rates_per_million'][0]+(q['max_output_tokens']or 0)*q['reservation_rates_per_million'][1])/1e6
            evidence['requests'].append(q)
            raw=response(old['raw_response'])
            evidence['observations'].append(dict(request_id=rid,response=raw,sanitized_response_sha256=sha(canonical(raw)),
                original_raw_response_sha256=old['raw_output_sha256'],seconds=old['seconds'],
                physical_cost_usd=old['recorded_usd'],new_cost_usd=0,fresh=False,http_status=200,error=old['error'],
                historical_observation_sha256=old['observation_file_sha256']))
    # Archive implementation and its entire local Python import closure, including dynamic runner imports.
    scripts=['trace_followup.py','coverage_round2.py','root_trace_run.py','export_final_evidence.py',
             'data.py','extract_context.py','experiment.py','trace_evaluate.py','score_coverage_round2.py',
             'funded-rounds/round2/root_runner_v2.py']
    sources={ 'lab/'+p:(base/p) for p in scripts}
    foreign={
      'lab/harness.py':root/'jobs/experiment-agentic-judge/.lab-results/agentic-claude/harness.py',
      'lab/jev_probe_adapter.py':root/'jobs/judge-operations/.lab-results/judge-operations/jev_probe_adapter.py',
      'lab/queue_judges.py':root/'jobs/judge-operations/.lab-results/judge-operations/queue_judges.py',
      'lab/validate_mixed_queue.py':root/'jobs/judge-operations/.lab-results/judge-operations/validate_mixed_queue.py'}
    sources.update(foreign)
    for sub in ('src/dry_lint','scripts/research_mining'):
        for p in (work/sub).rglob('*.py'):sources[str(p.relative_to(work))]=p
    for name in ('pyproject.toml','uv.lock','LICENSE'):sources[name]=work/name
    archive={}
    for name,p in sorted(sources.items()):
        raw=p.read_bytes()
        archive[name]=dict(sha256=sha(raw),text=raw.decode())
    dump(dest/'implementation.json.gz',archive)
    # Port copies of the exact transform and constant prompt literals, no lab imports.
    source=(base/'coverage_round2.py').read_text();node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='windows')
    (dest/'transforms.py').write_text('"""Exact frozen windows() implementation; Apache-2.0, Gigaverse. See implementation archive."""\nfrom common import sha\n\n'+ast.get_source_segment(source,node)+'\n')
    prompt_source=(work/'src/dry_lint/judges/command.py').read_text()
    literals={}
    for n in ast.parse(prompt_source).body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='OPERATIONS_PROMPT' for t in n.targets):
            literals['claude_shared_operations']=ast.literal_eval(n.value)
    literals['jev_questions']=read(base/'questions.json')['baseline']
    source=(work/'src/dry_lint/judges/jev.py').read_text()
    for n in ast.parse(source).body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REASONS' for t in n.targets):
            literals['jev_generated_reasons']=ast.literal_eval(n.value)
    dump(dest/'prompts.json',literals)
    evidence['source_region_coverage']=read(rounds['R2']/'CONTROL-REGION-COVERAGE.json')
    # Retain original published numeric evidence and CSV for independent agreement checks.
    published=root/'jobs/research-evidence-publication/docs/research/funded-recall/context'
    evidence['published']=read(published/'evidence.json')
    (dest/'published-paired-results.csv').write_bytes((published/'paired-results.csv').read_bytes())
    dump(dest/'recordings.json.gz',evidence);dump(dest/'source-files.json.gz',dict(blobs=public_files,index=source_index,trees=trees))
    pins=[]
    licenses=dest/'licenses';licenses.mkdir(exist_ok=True)
    for r in repositories:
        pin={k:r[k] for k in ('repository','revision')};pin['url']='https://github.com/'+r['repository']+'.git'
        if r['repository']=='Garsson-io/kaizen':
            pin['redistribution']='held; source excluded; hydrate locally'
        else:
            lic=blob(r['git'],r['revision'],'LICENSE')
            path=licenses/(r['repository'].replace('/','--')+'.txt');path.write_bytes(lic)
            pin['license_file']=str(path.relative_to(dest));pin['license_sha256']=sha(lic)
        pins.append(pin)
    (licenses/'dry-lint-Apache-2.0.txt').write_bytes((work/'LICENSE').read_bytes())
    dump(dest/'source-pins.json',pins)
    print(canonical(dict(requests=len(evidence['requests']),observations=len(evidence['observations']),cases=len(evidence['cases']),
         public_rendered_requests=sum('exact_rendered_json'in q for q in evidence['requests']),
         source_files=len(public_files),implementation_files=len(archive))))
if __name__=='__main__':main()
