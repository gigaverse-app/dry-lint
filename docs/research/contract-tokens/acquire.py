#!/usr/bin/env python3
"""Print pinned public acquisition instructions or verify an already acquired corpus."""
import argparse,json,subprocess
from pathlib import Path
from reproduce import read,sha
p=argparse.ArgumentParser();p.add_argument('--corpus',type=Path);a=p.parse_args();c=read('CORPUS.json')
if a.corpus:
    commit=subprocess.check_output(['git','-C',str(a.corpus),'rev-parse','HEAD'],text=True).strip()
    assert commit==c['corpus_commit'],(commit,c['corpus_commit'])
    assert sha((a.corpus/'catalog.json').read_bytes())==c['catalog_sha256']
    catalog=json.loads((a.corpus/'catalog.json').read_bytes());checked=0
    for b in c['backgrounds']:
        for match in b['catalog_matches']:
            entry=catalog['datasets'][match['dataset']];raw=(a.corpus/entry['manifest']).read_bytes();assert sha(raw)==entry['sha256']
            file=json.loads(raw)['files'][match['path']];assert file['sha256']==b['study_background_sha256'];checked+=1
    print(json.dumps({'status':'PASS','exact_background_catalog_bindings':checked,'scope':'Catalog hash lookup; run corpus.py verify for stored object bytes. Missing/private study inputs remain missing/private.'}))
else:
    print('git clone https://github.com/gigaverse-app/dry-lint-goldens.git local-corpus')
    print('git -C local-corpus checkout --detach '+c['corpus_commit'])
    print('python3 local-corpus/corpus.py verify')
    for ds in sorted({x['dataset']for b in c['backgrounds']for x in b['catalog_matches']}):print('python3 local-corpus/corpus.py materialize '+ds+' --out local-'+ds)
    print('python3 acquire.py --corpus local-corpus')
