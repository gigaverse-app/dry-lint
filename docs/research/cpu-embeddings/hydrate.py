#!/usr/bin/env python3
"""Verify or hydrate exact selected source from a caller-supplied local Git repository. No fetch."""
import argparse
import json
import subprocess
from pathlib import Path
from reproduce import read,sha,check

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository',required=True)
    p.add_argument('--git',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    pins={x['repository']:x for x in read('data/source-pins.json')}
    if args.repository=='Garsson-io/kaizen':
        pin=read('data/holds.json')['redistribution_hold']['revision']
        actual=subprocess.check_output(['git','-C',str(args.git),'rev-parse',pin+'^{commit}'],text=True).strip()
        check(actual==pin,'Exact held source commit missing')
        check(not args.output.exists(),'Use a new caller-owned output directory')
        args.output.mkdir(parents=True)
        # Held corpus source stays local. Export exact commit, not a floating checkout or nearest revision.
        with (args.output/'source.tar').open('wb') as out:
            subprocess.run(['git','-C',str(args.git),'archive',pin],stdout=out,check=True)
        (args.output/'LOCAL-ONLY.json').write_text(json.dumps({'repository':args.repository,'revision':pin,'redistribution':'held; do not publish','selected_method_replay':'Historical complete-background artifacts still required; see manifest.'},indent=2))
        print('Exact held snapshot hydrated locally; do not redistribute.');return
    pin=pins[args.repository]['revision']
    check(not args.output.exists(),'Use a new caller-owned output directory')
    args.output.mkdir(parents=True)
    count=0
    for h,s in read('data/source-files.json.gz').items():
        if s['repository']!=args.repository:continue
        data=subprocess.check_output(['git','-C',str(args.git),'show',pin+':'+s['path']])
        check(sha(data)==h,'Exact file hash mismatch')
        target=args.output/s['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);count+=1
    print(json.dumps({'verified_files':count,'repository':args.repository,'revision':pin,'network_calls':0}))
if __name__=='__main__':main()
