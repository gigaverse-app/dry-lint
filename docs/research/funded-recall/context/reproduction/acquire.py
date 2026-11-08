#!/usr/bin/env python3
"""Print user-run immutable Git fetch commands, or verify already acquired objects. Never fetch automatically."""
import argparse
import shlex
import subprocess
from pathlib import Path
from common import canonical, read, sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,default=Path('local-sources'))
    p.add_argument('--verify',action='store_true')
    a=p.parse_args();pins=read('source-pins.json');data=read('recordings.json.gz')
    if not a.verify:
        print('set -eu')
        for pin in pins:
            directory=a.directory/pin['repository'].replace('/','--')
            quote=shlex.quote
            print('git init --bare '+quote(str(directory)))
            print('git -C '+quote(str(directory))+' -c core.hooksPath=/dev/null fetch --depth=1 '+quote(pin['url'])+' '+pin['revision'])
        return
    checked=0
    for pin in pins:
        directory=a.directory/pin['repository'].replace('/','--')
        def git(*args):
            return subprocess.check_output(['git','--no-replace-objects','-C',str(directory),*args],stderr=subprocess.PIPE)
        if git('rev-parse',pin['revision']+'^{commit}').decode().strip()!=pin['revision']:
            raise ValueError('Source commit mismatch: '+pin['repository'])
        for case in data['cases']:
            if case['repository']!=pin['repository']:continue
            for proof in case['source_proofs']:
                raw=git('cat-file','blob',pin['revision']+':'+proof['path'])
                if sha(raw)!=proof['file_sha256']:raise ValueError('Source file mismatch: '+proof['path'])
                checked+=1
    print(canonical(dict(status='PASS',pinned_repositories=len(pins),endpoint_file_checks=checked,network_calls=0)))

if __name__=='__main__':main()
