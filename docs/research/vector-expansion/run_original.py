#!/usr/bin/env python3
"""Explicit optional full-background run of original pure vector algorithms; no provider code."""
import argparse,ast,gzip,hashlib,json,math,os,time
from collections import Counter,defaultdict
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from reproduce import read
from transform import original_index

def main():
    p=argparse.ArgumentParser();p.add_argument('--background',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--method',choices=['sparse','latent'],default='sparse');a=p.parse_args()
    assert os.environ.get('PYTHONHASHSEED')=='0','Run with PYTHONHASHSEED=0'
    assert not a.out.exists(),'Output must be new; original evidence is immutable'
    for name in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS']:os.environ[name]='2'
    import numpy as np
    from scipy.sparse import csr_matrix,save_npz,load_npz
    raw=a.background.read_bytes();h=hashlib.sha256(raw).hexdigest();assert h in {r['study_background_sha256']for r in read('CORPUS.json')['backgrounds']},'Not an exact study background'
    bg=json.loads(gzip.decompress(raw));cls=original_index()
    class Document:
        def __init__(self,d):self.id=d['id'];self.counts=d['counts']
        def tokens(self):return [t for t,n in self.counts.items()for _ in range(n)]
    docs=[Document(d)for d in bg['documents']]
    background=SimpleNamespace(documents=docs,index=lambda:cls([d.tokens()for d in docs],bg['max_df']))
    archive=read('data/implementation.json.gz');a.out.mkdir(parents=True)
    spec=archive['lab/funded-rounds/round2/EXPERIMENT.json']['text'];(a.out/'EXPERIMENT.json').write_text(spec)
    ns=dict(np=np,csr_matrix=csr_matrix,save_npz=save_npz,load_npz=load_npz,os=os,time=time,hashlib=hashlib,json=json,math=math,Counter=Counter,defaultdict=defaultdict,combinations=combinations,Path=Path,O=a.out,ALGORITHM='herdr-source-pmi-onehop-r2-v1',sha=lambda b:hashlib.sha256(b).hexdigest(),dump=lambda p,x:p.write_text(json.dumps(x,indent=2)+'\n'))
    def definitions(key,names):
        nodes=[n for n in ast.parse(archive[key]['text']).body if isinstance(n,ast.FunctionDef)and n.name in names]
        assert {n.name for n in nodes}==set(names)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'archived:'+key,'exec'),ns)
    definitions('lab/full-corpus/vector_engine.py',['matrix','fit'])
    if a.method=='sparse':
        definitions('lab/funded-rounds/round2/source_pmi.py',['build']);_,_,_,info=ns['build'](background,h,a.out/'fit')
    else:
        _,X,_=ns['matrix'](background);_,_,_,info=ns['fit'](X,a.out/'latent.npz',h)
    print(json.dumps({'background_sha256':h,'method':a.method,'fit':info,'scope':'Original representation fitting for this one exact background only; not campaign nomination, funding or semantic evaluation.'},indent=2))
if __name__=='__main__':main()
