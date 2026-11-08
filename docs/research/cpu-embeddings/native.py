#!/usr/bin/env python3
"""Run the original cosine algorithm on eight recorded public-source embedding rows. No encoding."""
import ast
import json
import math
from types import SimpleNamespace
from reproduce import HERE,read,sha,check

def main():
    import numpy as np
    path=HERE/'data/original/product/src/dry_lint/cpu_embedding.py.txt'
    tree=ast.parse(path.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CpuEmbeddingComparer')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='similarity')
    ns={};module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),fn],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(path),'exec'),ns)
    cases={c['id']:c for c in read('data/recordings.json')['cases']};results=[]
    for c in read('data/selected-vectors.json')['cases']:
        matrix=np.asarray([v['vector'] for v in c['vectors']],dtype=np.float32)
        check(matrix.shape==(2,384) and np.isfinite(matrix).all(),'Recorded vector shape')
        fs=[SimpleNamespace(**cases[c['id']]['candidate'][v['side']]) for v in c['vectors']]
        for f,v in zip(fs,c['vectors']):check(sha(f.code)==v['body_sha256'],'Recorded vector source binding')
        def vectors(codes):
            check(codes==[f.code for f in fs],'Exact recorded bodies required')
            return matrix
        actual=ns['similarity'](SimpleNamespace(_vectors=vectors),*fs)
        check(math.isclose(actual,c['recorded_full_background_cosine'],abs_tol=1e-6),'Original cosine parity')
        results.append({'id':c['id'],'cosine':actual,'recorded':c['recorded_full_background_cosine']})
    print(json.dumps({'status':'PASS','original_algorithm':'CpuEmbeddingComparer.similarity (unchanged AST)','pairs':results,'encodes':0,'refits':0,'scope':'Pair cosine only. Original full-background rank and eligible top20 reranking are not recomputed from a two-vector subset.'},indent=2))
if __name__=='__main__':main()
