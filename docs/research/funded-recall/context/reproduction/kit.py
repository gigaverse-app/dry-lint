#!/usr/bin/env python3
"""Readable entrypoint: inspect-case CASE --kind jev|claude --arm baseline|treatment."""
import argparse
from inspect_case import show

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['inspect-case'])
    p.add_argument('case')
    p.add_argument('--round',choices=['R1','R2'])
    p.add_argument('--kind',choices=['jev','claude'],default='claude')
    p.add_argument('--arm',choices=['baseline','treatment'],default='treatment')
    p.add_argument('--part',choices=['all','original','git','input','prompt','answer'],default='all')
    p.add_argument('--side',choices=['new','existing','both'],default='both')
    show(p.parse_args())
if __name__=='__main__':main()
