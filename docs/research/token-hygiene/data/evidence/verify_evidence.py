"""Recompute published paired counts using only this portable, redacted evidence."""
import gzip,hashlib,json,random
from collections import defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
def main():
 metrics=json.loads((HERE/'metrics.json').read_text());groups=defaultdict(dict);accepted_raw=set();lines=0
 with gzip.open(HERE/'paired-rows.jsonl.gz','rt') as stream:
  for line in stream:
   r=json.loads(line);lines+=1;a=r['baseline'];v=r['variant']
   if r['accepted_gold'] and r['record_kind']=='function' and a['raw_supported'] and v['raw_supported']:accepted_raw.add(r['row_uid'])
   if not(r['accepted_gold'] and r['current_binary_eligible'] and r['record_kind']=='function' and a['raw_supported'] and v['raw_supported']):continue
   key=r['arm'],r['profile'],r['label'];groups[key].setdefault(r['pair_background_uid'],r)
 checks=0
 for expected in metrics['comparisons']:
  rs=list(groups[(expected['arm'],expected['profile'],expected['label'])].values());assert len(rs)==expected['unique_pairs']
  for name,want in expected['metrics'].items():
   supported=[r for r in rs if r['baseline'][name] is not None and r['variant'][name] is not None]
   got=dict(supported_pairs=len(supported),missing_pairs=len(rs)-len(supported),baseline=sum(r['baseline'][name] for r in supported),variant=sum(r['variant'][name] for r in supported),gains=sum(r['variant'][name] and not r['baseline'][name] for r in supported),losses=sum(r['baseline'][name] and not r['variant'][name] for r in supported),repository_family_blocks=len({r['family_uid'] for r in supported}))
   assert all(got[k]==want[k] for k in got),(expected['arm'],expected['profile'],expected['label'],name,got,want)
   if want['repository_family_bootstrap95'] is not None:
    blocks=defaultdict(list)
    for r in supported:blocks[(r['repository_uid'],r['family_uid'])].append(r)
    byrepo=defaultdict(list)
    for (repo,family),family_rows in blocks.items():byrepo[repo].append(family_rows)
    order={r['repository_uid']:r['repository_order'] for r in supported};repos=sorted(byrepo,key=lambda repo:order[repo])
    if got['gains']==got['losses']==0:interval=[0.0,0.0]
    else:
     rng=random.Random(20261107);reps=[]
     for _ in range(2000):
      sample=[]
      for repo in rng.choices(repos,k=len(repos)):
       fs=byrepo[repo]
       for family in rng.choices(fs,k=len(fs)):sample+=family
      reps.append(sum(int(r['variant'][name])-int(r['baseline'][name]) for r in sample)/len(sample))
     reps.sort();interval=[reps[49],reps[1949]]
    assert interval==want['repository_family_bootstrap95'],('bootstrap',expected['arm'],expected['profile'],expected['label'],name,interval,want['repository_family_bootstrap95'])
   checks+=1
 assert lines==metrics['evidence']['paired_export_rows'];assert len(accepted_raw)==580
 if (HERE/'MANIFEST.json').exists():
  for item in json.loads((HERE/'MANIFEST.json').read_text())['files']:
   assert hashlib.sha256((HERE/item['name']).read_bytes()).hexdigest()==item['sha256'],item['name']
 print(json.dumps(dict(status='verified',paired_rows=lines,accepted_function_rows_raw=580,paired_metric_checks=checks,provider_calls=0)))
if __name__=='__main__':main()
