#!/usr/bin/env python3
"""Explicit local-only hydration of held source by exact Git character maps. Never fetches."""
import argparse,json,subprocess
from pathlib import Path
from reproduce import read,sha
p=argparse.ArgumentParser();p.add_argument('--git',type=Path);p.add_argument('--case');p.add_argument('--out',type=Path);a=p.parse_args();records=read('data/held-request-templates.json')
if not a.git or not a.case or not a.out:
    print(json.dumps({'held_cases':sorted({r['id']for r in records}),'plan':'Acquire the public repository and exact revision from data/source-manifest.json; then python3 hydrate.py --git /path/to/repo --case CASE_ID --out local-held-CASE_ID. This reads Git objects without checkout or target execution. Output must be new; keep it local. This reconstructs original cached extraction character maps, not a fresh parser run.'},indent=2));raise SystemExit()
chosen=[r for r in records if r['id']==a.case];assert chosen,'No held case';assert not a.out.exists(),'Output must be new'
result=[]
for r in chosen:
    values={}
    for b in r['bindings']:
        raw=subprocess.check_output(['git','-C',str(a.git),'show',r['revision']+':'+b['path']]);assert sha(raw)==b['file_sha256']
        text=raw.decode();value=''.join(x['separator']if 'separator'in x else text[x['start']:x['end']]for x in b['parts']);assert sha(value)==b['sha256'];values[b['marker']]=value
    template=r['template']
    if r['format']=='json-fields':
        obj=json.loads(template)
        for side in obj['state'].values():
            if isinstance(side,dict):
                for k in ['code','source_context']:
                    if k in side and side[k] in values:side[k]=values[side[k]]
        rendered=json.dumps(obj)
    else:
        rendered=template
        for marker,value in values.items():rendered=rendered.replace(marker,value)
    assert sha(rendered)==r['rendered_sha256']
    identity=dict(r['identity_without_rendered'],rendered_input=rendered)
    assert sha(json.dumps(identity,sort_keys=True,ensure_ascii=True,allow_nan=False))==r['request_key']
    result.append({'id':r['id'],'kind':r['kind'],'identity':identity,'request_key':r['request_key']})
a.out.mkdir(parents=True);(a.out/'requests.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':'PASS','exact_requests':len(result),'output':str(a.out),'redistribution':'held; do not publish hydrated source'}))
