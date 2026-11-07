#!/usr/bin/env python3
"""Inspect original implementation without importing or executing it."""
import argparse
from common import read, sha
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['list','show'])
    p.add_argument('name',nargs='?')
    a=p.parse_args();archive=read('implementation.json.gz')
    if a.command=='list':
        for name,entry in archive.items():print(entry['sha256'],name)
    else:
        entry=archive[a.name]
        if sha(entry['text'])!=entry['sha256']:raise ValueError('Archived code hash mismatch')
        print(entry['text'],end='')
if __name__=='__main__':main()
