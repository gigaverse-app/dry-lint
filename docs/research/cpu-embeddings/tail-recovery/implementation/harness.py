"""Offline PR109 route replay. Whole native Candidates, independent ledgers, exact ranks."""
from common import *
import time
import numpy as np
from collections import Counter
from dry_lint.cpu_embedding import CpuEmbeddingComparer
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor
from dry_lint.settings import Settings
from dry_lint.costs import Ledger,estimate
from dry_lint.judges.command import prompt,PROMPT_POLICIES
from dry_lint.judges.jev import CONTEXT_QUESTIONS,CONTEXT_PROMPT_VERSION,state
from dry_lint.models import pair_key,Candidate
class ClaudeEstimate:
    name='anthropic-operations';model='claude-sonnet-5-5';version=PROMPT_POLICIES['shared-operations'][0]+':claude-sonnet-5-5:output=1024'
    prompt_policy='shared-operations';max_tokens=1024;subscription=False
    def input_text(self,c):return prompt(c,policy=self.prompt_policy)
class JevEstimate:
    name='jev';model='jev-1.14.0';version=CONTEXT_PROMPT_VERSION+':jev-1.14.0';max_tokens=None;subscription=False
    def input_text(self,c):return json.dumps({'model':self.model,'state':state(c,True),'questions':CONTEXT_QUESTIONS})
CLAUDE=ClaudeEstimate();JEV=JevEstimate()
class OperationIndex:
    name='cpu-complete-statements';version='1';similarity_reusable=False;discovery_unseen=True
    def __init__(self,fs,prefix,views,owners):
        self.functions=fs;self.prefix=prefix;self.views=views;self.owners=owners
        self.position={f.qualname:i for i,f in enumerate(fs)}
        self.ambiguous={k for k,v in Counter(f.qualname for f in fs).items() if v>1}
        self.cached_query=None;self.cached_scores=None
    def index(self,fs):assert fs is self.functions
    def scores(self,f):
        i=self.position[f.qualname]
        if self.cached_query==i:return self.cached_scores
        # Only operation-bearing comparisons: prefix-prefix belongs to original route.
        scores=np.full(len(self.functions),-1.,dtype=np.float32)
        own=self.views[self.owners==i]
        if len(own):scores=np.maximum(scores,(self.prefix@own.T).max(axis=1))
        if len(self.views):
            queries=np.vstack([self.prefix[i:i+1],own]);v=(self.views@queries.T).max(axis=1)
            np.maximum.at(scores,self.owners,v)
        self.cached_query=i;self.cached_scores=scores
        return scores
    def neighbours(self,f,k,allowed):
        if k<=0 or f.qualname in self.ambiguous or f.line<1:return []
        result=[]
        for j in np.argsort(-self.scores(f),kind='stable'):
            g=self.functions[j];score=float(self.cached_scores[j])
            if score<.8:break
            if g.qualname!=f.qualname and g.qualname not in self.ambiguous and g.line>=1 and allowed(g):
                result.append((g,min(1.,score)))
                if len(result)==k:break
        return result
    def similarity(self,a,b):return max(0.,min(1.,float(self.scores(a)[self.position[b.qualname]])))
class Replay:
    def __init__(self,folder):
        start=time.perf_counter();self.folder=folder
        self.manifest,self.bg,self.fs,self.native=load(folder)
        fs=self.fs;self.settings=Settings(include=self.bg.scope['include'],exclude=self.bg.scope['exclude'],budget={'usd':.04},discovery={'enabled':False})
        extractors=[PythonExtractor(),TypeScriptExtractor()]
        self.base=Detector(fs,self.settings,TfidfComparer(max_df=self.bg.max_df),extractors)
        wide_settings=self.settings.model_copy(update={'neighbours':20})
        self.wide=Detector(fs,wide_settings,TfidfComparer(min_similarity=.35,min_similarity_small=.35,max_df=self.bg.max_df),extractors,same_file=True)
        self.prefix=CpuEmbeddingComparer(str(OLD/'model-cache'))
        vec=np.load(folder/'embeddings.npy',allow_pickle=False)
        assert vec.shape==(len(fs),384)
        self.prefix._bodies={f.code:v for f,v in zip(fs,vec,strict=True)}
        one_settings=self.settings.model_copy(update={'neighbours':1})
        self.cpu=Detector(fs,one_settings,self.prefix,extractors,same_file=True,discovery_keys=set())
        assert self.prefix.cache_misses==0
        # Equivalent memoization across routes and repeated endpoints; no ranking change.
        tfidf=self.base.comparer.tfidf
        original_similar=tfidf.similar
        memo={}
        def cached_similar(document,limit=None,exclude=frozenset()):
            key=(tuple(document),frozenset(exclude))
            if key not in memo:
                memo.clear();memo[key]=original_similar(document,exclude=exclude)
            return memo[key][:limit]
        tfidf.similar=cached_similar
        self.wide.comparer.tfidf=tfidf
        original_hashed=self.base.hashed
        hashes={}
        def cached_hashed(function):
            key=(function.qualname,sha(function.code.encode()))
            if key not in hashes:hashes[key]=original_hashed(function)
            return hashes[key]
        self.base.hashed=self.wide.hashed=self.cpu.hashed=cached_hashed
        out=HERE/'cohorts'/folder.name
        data=np.load(out/'view-vectors.npz',allow_pickle=False)
        self.op=OperationIndex(fs,vec,data['vectors'],data['owners'])
        self.tail=Detector(fs,one_settings,self.op,extractors,same_file=True,discovery_keys=set())
        self.tail.hashed=cached_hashed
        self.position={f.qualname:i for i,f in enumerate(fs)}
        self.views=read(out/'views.jsonl');self.index_seconds=time.perf_counter()-start
    def proposals(self,q):
        base=[self.base.pair(q,f,s) for f,s in self.base.neighbours(q)]
        keys={c.key for c in base};wide=[]
        for f,s in self.wide.neighbours(q):
            c=self.wide.pair(q,f,s)
            if c.key not in keys:keys.add(c.key);wide.append(c.model_copy(update={'lane':'exploration'}))
        self.cpu.discovery_keys=keys
        prefix=[self.cpu.pair(q,f,s).model_copy(update={'lane':'exploration'}) for f,s in self.cpu.neighbours(q)]
        original=base+wide+prefix
        self.tail.discovery_keys={c.key for c in original}
        operation=[self.tail.pair(q,f,s).model_copy(update={'lane':'exploration'}) for f,s in self.tail.neighbours(q)] if not prefix else []
        return {'baseline3':base,'wide':base+wide,'original':original,'treatment':original+operation}
    def ledger(self,candidates,paired=True):
        # Match canonical contract: full normal estimates for both kinds, no physical-cache discount.
        total=0.;rows=[]
        for i,c in enumerate(candidates,1):
            charge=estimate(CLAUDE,[c],self.settings)+(estimate(JEV,[c],self.settings) if paired else 0.)
            reason='filtered:'+c.filtered if c.filtered else 'unknown_native_span' if min(c.new.line,c.existing.line)<1 else 'budget' if total+charge>.04 else None
            admitted=reason is None
            if admitted:total+=charge
            rows.append({'ordinal':i,'candidate':c.model_dump(mode='json'),'admitted':admitted,'reason':reason or 'normal_estimate_within_cap','normal_charge_usd':charge,'cumulative_usd':total,'cap_usd':.04})
        if not paired:
            eligible=[c for c in candidates if not c.filtered and min(c.new.line,c.existing.line)>=1]
            ledger=Ledger(self.settings);selected=ledger.select(CLAUDE,eligible)
            assert [eligible[i].key for i in selected]==[Candidate.model_validate(r['candidate']).key for r in rows if r['admitted']]
        return rows
    def ranks(self,q,target,arms):
        i=self.position[q.qualname];j=self.position[target.qualname]
        sparse=self.base.comparer.tfidf.similar(q.tokens,exclude={i});sparse_scores=dict(sparse)
        dense=self.prefix.vectors@self.prefix.vectors[i];op=self.op.scores(q)
        def ranks(order):
            raw=[n for n in order if n!=i]
            cross=[n for n in raw if self.fs[n].path!=q.path]
            language=[n for n in raw if self.base.file_extractors[self.fs[n].path] is self.base.file_extractors[q.path]]
            return {'raw_nonself':raw.index(j)+1 if j in raw else None,'crossfile':cross.index(j)+1 if j in cross else None,'same_extractor_nonself':language.index(j)+1 if j in language else None}
        key=pair_key(q.qualname,target.qualname)
        funded={arm:{Candidate.model_validate(r['candidate']).key for r in self.ledger(cs) if r['admitted']} for arm,cs in arms.items()}
        sparse_score=sparse_scores.get(j,0.)
        stages={}
        for arm,cs in arms.items():
            c=next((c for c in cs if c.key==key),None)
            if q.line<1 or target.line<1:loss='native_source'
            elif arm=='baseline3' and q.path==target.path:loss='same_file'
            elif c and c.filtered:loss='rule_filter:'+c.filtered
            elif c:loss='retained' if key in funded[arm] else 'budget'
            elif arm=='baseline3':loss='score_floor' if sparse_score<self.base.comparer.floor(q) else 'top3'
            elif arm=='wide':loss='score_floor' if sparse_score<.35 else 'top20'
            elif arm=='original':loss='prefix_score_floor' if dense[j]<.65 else 'earlier_route_or_top1'
            else:loss='original_route_did_not_abstain' if len(arms['original'])>len(arms['wide']) else 'operation_score_floor' if op[j]<.8 else 'earlier_route_or_top1'
            stages[arm]={'retrieved':c is not None,'funded':key in funded[arm],'first_loss':loss}
        return {'query':q.qualname,'target':target.qualname,'query_lines':q.lines,'samefile':q.path==target.path,'size_ratio_floor':None,'minimum_lines':'existing native extraction policy only','baseline_floor':self.base.comparer.floor(q),'tfidf':{'score':sparse_score,**ranks([n for n,s in sparse])},'prefix':{'score':float(dense[j]),**ranks(np.argsort(-dense,kind='stable').tolist())},'operation':{'score':float(op[j]),**ranks(np.argsort(-op,kind='stable').tolist())},'stages':stages,'query_views':self.views[i],'target_views':self.views[j]}
