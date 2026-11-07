#!/usr/bin/env python3
"""Restore archived original implementation as readable runnable files in a new directory; never execute it."""
import argparse
from pathlib import Path
from reproduce import HERE,read,sha,check

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--lab-root',type=Path,required=True,help='Explicit isolated root used to replace normalized LAB_ROOT references.')
    a=p.parse_args();check(not a.output.exists(),'Use a new directory');a.output.mkdir(parents=True)
    files=0
    for r in read('data/provenance.json'):
        if 'published_path' not in r:continue
        path=HERE/r['published_path'];text=path.read_text();check(sha(text)==r['published_sha256'],'Archived code hash')
        rel=Path(r['published_path']).relative_to('data/original')
        target=a.output/str(rel).removesuffix('.txt');target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(text.replace('LAB_ROOT',str(a.lab_root.resolve())))
        files+=1
    print(f'Restored {files} files. Product is under product/; experiment programs under lab/. Nothing executed.')
if __name__=='__main__':main()
