#!/usr/bin/env python3
"""Run frozen TF-IDF vector code and selected bounded transformations, offline."""
import ast
from collections import Counter, defaultdict
import json
import math
from reproduce import read

def original_index():
    text=read('data/implementation.json.gz')['src/dry_lint/index.py']['text']
    node=next(n for n in ast.parse(text).body if isinstance(n,ast.ClassDef) and n.name=='TfidfIndex')
    ns={'math':math,'Counter':Counter,'defaultdict':defaultdict}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'archived:TfidfIndex','exec'),ns)
    return ns['TfidfIndex']

def run():
    cls=original_index();out=[]
    for case in read('data/transform-inputs.json'):
        before=[];after=[]
        for side in case['sides']:
            index=cls.__new__(cls);index.idf=side['idf']
            tokens=[t for t,n in side['counts'].items() for _ in range(n)]
            raw=index.vector(tokens);before.append(raw)
            if 'selected_edges' in side and side['selected_edges']:
                # Execute the original selected-contribution loop, without its fitting/IO top level.
                source=read('data/implementation.json.gz')['lab/funded-rounds/round2/source_pmi.py']['text']
                build=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='build')
                loop=next(n for n in build.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(row, picked)')
                retained={}
                for e in side['selected_edges']:
                    retained.setdefault(e['anchor'],[]).append((e['target'],e['log2_PMI'],e['function_support']))
                ns={'anchors':[[(t,raw[t])for t in retained]],'retained':retained,'expanded_rows':0,'added_i':[],'added_j':[],'added_v':[]}
                exec(compile(ast.Module(body=[loop],type_ignores=[]),'archived:source_pmi contribution loop','exec'),ns)
                transformed=dict(raw)
                for t,v in zip(ns['added_j'],ns['added_v']):transformed[t]=transformed.get(t,0)+v
                length=math.sqrt(sum(v*v for v in transformed.values()))or 1
                transformed={t:v/length for t,v in transformed.items()}
            elif case.get('method')=='vector-expansion':
                transformed=raw
            else:
                # Original evaluate.py recipe: only body-word term counts become one.
                counts={t:1 if t.startswith('w:')else n for t,n in side['counts'].items()}
                transformed=index.vector([t for t,n in counts.items()for _ in range(n)])
            want=side['expected_transformed_vector']
            assert set(transformed)==set(want)
            assert all(abs(transformed[t]-want[t])<1e-12 for t in want)
            after.append(transformed)
        dot=lambda a,b:sum(v*b.get(k,0)for k,v in a.items())
        b=dot(*before);a=dot(*after)
        assert abs(b-case['expected_raw_cosine'])<1e-12
        assert abs(a-case['expected_transformed_cosine'])<1e-12
        out.append({'id':case['id'],'before_cosine':b,'after_cosine':a,'background_functions':case['background_functions'],'scope':case['scope_limit']})
    return out
if __name__=='__main__':print(json.dumps(run(),indent=2))
