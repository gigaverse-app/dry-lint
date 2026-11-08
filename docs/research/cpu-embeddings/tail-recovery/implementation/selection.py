"""Methodblind, answer-free source exclusions and deterministic cohort selection."""
from common import *
from register import family,split
from dry_lint.models import Candidate
from collections import defaultdict,Counter

def endpoints(candidate):
    c=Candidate.model_validate(candidate)
    return tuple(sorted((f.qualname,sha(f.code.encode())) for f in (c.new,c.existing)))
def prior_sources():
    paths=[OLD/'full-corpus/shared-inputs/9bfa15c84eb72dd2/rows.jsonl']
    paths+=list((ROOT/'reports/research-experiments').rglob('*provider-feed.jsonl'))
    paths+=list(OLD.rglob('provider-queue.jsonl'))
    paths+=list(OLD.glob('novel-review-queue.jsonl'))
    return sorted(set(paths))
def known():
    pairs=set();families=set();proof=[]
    for path in prior_sources():
        proof.append({'path':str(path),'sha256':sha(path.read_bytes())})
        for row in read(path):
            packet=row.get('packet') or row
            if not packet.get('candidate'):continue
            repo=packet.get('repository') or row.get('repository');rev=packet.get('revision') or row.get('revision')
            if not repo or not rev:continue
            pairs.add((repo,rev,endpoints(packet['candidate'])))
            for side in ['new','existing']:families.add(family(repo,packet['candidate'][side]['path']))
    return pairs,families,proof

def eligibility(row,knownpairs,knownfamilies,phase='development'):
    c=Candidate.model_validate(row['candidate']);repo=row['repository'];rev=row['revision']
    if (repo,rev,endpoints(row['candidate'])) in knownpairs:return 'exact_previously_frozen_or_reviewed_pair'
    if max(len(c.new.code),len(c.existing.code))>8000:return 'canonical_jev_full_function_limit_8000'
    fs=[family(repo,f.path) for f in [c.new,c.existing]]
    if any(split(f)!=phase for f in fs):return 'family_split_other_or_cross'
    if phase=='confirmation' and any(f in knownfamilies for f in fs):return 'previously_reviewed_family_not_fresh_confirmation'
    return None

def select(rows,n,used=None):
    used=set() if used is None else used
    grouped=defaultdict(list)
    for r in rows:grouped[r['repository']].append(r)
    for group in grouped.values():group.sort(key=lambda r:sha(json.dumps([r['repository'],r['revision'],endpoints(r['candidate'])]).encode()))
    selected=[]
    while grouped and len(selected)<n:
        for repo in sorted(list(grouped)):
            group=grouped[repo]
            while group:
                r=group.pop(0);keys={(repo,name) for name,digest in endpoints(r['candidate'])}
                if not keys&used:
                    selected.append(r);used|=keys;break
            if not group:del grouped[repo]
            if len(selected)>=n:break
    return selected,used

if __name__=='__main__':
    knownpairs,knownfamilies,proof=known();dump(HERE/'known-review-exclusion.json',{'pairs':len(knownpairs),'families':sorted(knownfamilies),'inputs':proof})
    chosen=json.loads((HERE/'paid-source-cohorts.json').read_text())['cohorts'];inventory=[];counts=Counter()
    for repo,cfg in chosen.items():
        for role,filename in [('candidate','discovery-candidates.jsonl'),('control','discovery-controls.jsonl'),('rejected_audit','diagnosis.jsonl')]:
            path=HERE/'cohorts'/cfg['background']/filename
            if not path.exists():continue
            for row in read(path):
                reason=eligibility(row,knownpairs,knownfamilies)
                if role=='candidate' and not any(r['admitted'] and r['candidate']==row['candidate'] for r in row['ledgers']['treatment']):reason=reason or 'paired_04_unfunded'
                inventory.append({'repository':repo,'background':cfg['background'],'role':role,'pair':endpoints(row['candidate']),'exclusion':reason})
                counts[(role,reason or 'eligible')]+=1
    jsonl(HERE/'selection-audit.jsonl',inventory);dump(HERE/'selection-summary.json',{str(k):v for k,v in counts.items()})
