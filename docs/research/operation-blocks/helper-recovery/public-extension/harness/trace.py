"""Same-query first-loss measurements; no annotations inferred from outcomes."""
from dry_lint.operation_blocks import OperationBlocksComparer, _cosine
from dry_lint.detector import why_skipped
from dry_lint.settings import Settings


def trace(c,v,qi,ti,base):
    f,t=c.functions[qi],c.functions[ti]
    raw=c.tfidf.similar(f.tokens,exclude={qi})
    ranks={i:(n+1,score)for n,(i,score)in enumerate(raw)}
    cross=[(i,s)for i,s in raw if c.functions[i].path!=f.path]
    crossranks={i:n+1 for n,(i,s)in enumerate(cross)}
    result=dict(query=f.qualname,target=t.qualname,self_excluded=qi==ti or f.qualname==t.qualname,same_file=f.path==t.path,query_lines=f.lines,baseline_floor=.3 if f.lines<6 else .5,exploration_floor=.35,full_raw_rank_score=ranks.get(ti),cross_file_rank=crossranks.get(ti),pair_filter=why_skipped(f,t,Settings()),source_context_same_background=True)
    for label,cmp in [('original',c),('helper',v)]:
        qb=cmp._parents[qi];tb=cmp._parents[ti];pool=OperationBlocksComparer._pool(cmp,f,qb)
        score,shared=OperationBlocksComparer._best(qb,tb)
        whole=_cosine(c.tfidf.vector(f.tokens),c.tfidf.vector(t.tokens))
        first=('self'if f.qualname==t.qualname else'query_no_region'if not qb else'target_no_region'if not tb else'bounded_anchor_pool'if ti not in pool else'shared_operation_guard'if not score else'region_floor'if score<.65 else'whole_floor'if whole<.1 else'pair_filter'if result['pair_filter']else'already_preceding_route'if ti in base else'eligible')
        result[label]=dict(query_regions=len(qb),target_regions=len(tb),pool_rank=pool.index(ti)+1 if ti in pool else None,pool_size=len(pool),score=score,whole_score=whole,shared_operations=shared,first_loss=first,posting_visits=sum(len(cmp._postings.get(a,()))for b in qb for a in b.anchors),region_comparison_upper_bound=len(qb)*sum(len(cmp._parents[i])for i in pool))
    return result
