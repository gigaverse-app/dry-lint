#!/usr/bin/env python3
"""Recompute original and revised ranking metrics from anonymized paired records."""
import json,math
from reproduce import read
rows=read('data/paired-records.json.gz');metrics=read('data/evidence/FINAL-METRICS.json');checked=[]
for section,capture in [('original_methods','full-corpus/shared-span-v1-index-v2/paired-units.jsonl'),('association_metrics','funded-rounds/round2/regression/paired-units.jsonl')]:
    for want in metrics[section]:
        if want.get('cohort','ALL_PAIR_BACKGROUND_UNITS')!='ALL_PAIR_BACKGROUND_UNITS':continue
        rs=[r for r in rows if r['capture']==capture and r['accepted'] and r['label']==want['label']];arm=want['arm']
        mrr=sum(r['arms'][arm]['MRR']for r in rs)/len(rs);assert math.isclose(mrr,want.get('MRR',want.get('mean_reciprocal_rank')),abs_tol=1e-12)
        for name,expected in want['metrics'].items():
            if name.endswith('_funded'):continue # Different dataset/batch denominator: preserved in FINAL-METRICS.
            numerator=sum(r['arms'][arm][name] is True for r in rs);supported=sum(r['arms'][arm][name] is not None for r in rs)
            assert (numerator,supported)==(expected['numerator'],expected['supported']),(section,arm,name)
        checked.append({'capture':section,'label':want['label'],'arm':arm,'conditions':len(rs),'MRR':mrr,'top3':sum(r['arms'][arm]['top3']for r in rs),'top20':sum(r['arms'][arm]['top20']for r in rs)})
print(json.dumps({'status':'PASS','ranking_comparisons':checked,'funding_limit':'Dataset/batch funding is a separate preserved comparison, not recomputed by this rank aggregator.'},indent=2))
