#!/usr/bin/env python3
"""Replay pair/family aggregation from anonymized directional records, both windows."""
from collections import defaultdict
import json
from reproduce import read
rows=read('data/paired-records.json.gz');expected=read('data/evidence/metrics.json')['gold_comparison_round1_to_round2'];out=[]
for capture,prefix in [('original','r1'),('centered','r2')]:
    hits=defaultdict(set);families=defaultdict(set);denoms=defaultdict(set);famden=defaultdict(set)
    for r in rows:
        if r['capture']!=capture or not r['accepted'] or r['declaration_kind']!='function' or not r['directions']:continue
        label=r['label'];pk=r['pair_uid'];fam=r['family_uid'];denoms[label].add(pk);famden[label].add(fam)
        for d in r['directions']:
            if d['arm'] not in ['baseline','owner_0.15','shuffled_0.15']:continue
            for metric in ['top1','top3','top20','default','balanced']:
                yes=d[metric]if metric.startswith('top')else d['profiles'][metric]['funded']
                if yes:hits[label,d['arm'],metric].add(pk);families[label,d['arm'],metric].add(fam)
    for label in ['duplicate','separate']:
        assert len(denoms[label])=={'duplicate':31,'separate':51}[label]
        assert len(famden[label])=={'duplicate':28,'separate':37}[label]
        for metric in ['top1','top3','top20','default','balanced']:
            count=len(hits[label,'owner_0.15',metric]);assert count==expected[label][metric][prefix+'_owner_pairs']
            b=hits[label,'baseline',metric];v=hits[label,'owner_0.15',metric]
            out.append({'capture':capture,'label':label,'metric':metric,'supported_pairs':len(denoms[label]),'baseline':len(b),'owner':len(v),'gains':len(v-b),'losses':len(b-v)})
print(json.dumps({'status':'PASS','paired_comparisons':out},indent=2))
