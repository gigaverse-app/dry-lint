#!/usr/bin/env python3
"""Recompute qualified paired counts from anonymized directional regression records."""
from collections import defaultdict
import json
from reproduce import read
rs=read('data/paired-records.json.gz');groups=defaultdict(list)
for r in rs:
    if r['accepted_gold'] and r['label'] in ['duplicate','separate'] and any(d.get('status')=='evaluated' for d in r['directions']):groups[r['cohort_uid'],r['pair_uid'],r['label']].append(r)
def value(rr,arm,profile,metric):
    vals=[d['arms'][arm]['profiles'][profile][metric]for r in rr for d in r['directions']if d.get('status')=='evaluated']
    return True if True in vals else None if None in vals else False
out=[]
for want in read('data/evidence/revised-metrics.json')['strict_paired']:
    n=b=a=g=l=0
    for key,rr in groups.items():
        if key[2]!=want['label'] or not rr[0]['source_complete']:continue
        before=value(rr,'baseline',want['profile'],want['metric']);after=value(rr,'conjunction1',want['profile'],want['metric'])
        if before is None or after is None:continue
        n+=1;b+=before;a+=after;g+=after and not before;l+=before and not after
    got={'label':want['label'],'profile':want['profile'],'metric':want['metric'],'paired_supported_contexts':n,'baseline':b,'variant':a,'gains':g,'losses':l}
    assert all(want[k]==v for k,v in got.items()),(got,want)
    out.append(got)
print(json.dumps({'status':'PASS','paired_comparisons':out,'rows':len(rs)},indent=2))
