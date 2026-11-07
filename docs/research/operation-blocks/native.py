#!/usr/bin/env python3
"""Run original region extraction on selected recorded source; never refit a small replacement corpus."""
import ast
from collections import Counter,defaultdict,deque
from collections.abc import Iterator
from dataclasses import dataclass,field
import json
import re
from types import SimpleNamespace
from reproduce import HERE,read,check

def definitions(path,names,ns):
    tree=ast.parse((HERE/path).read_text());selected=[]
    for n in tree.body:
        targets={n.name} if isinstance(n,(ast.ClassDef,ast.FunctionDef)) else {t.id for t in n.targets if isinstance(t,ast.Name)} if isinstance(n,ast.Assign) else set()
        if targets & names:selected.append(n)
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*selected],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(path),'exec'),ns)

def main():
    ns={'__name__':__name__,'ast':ast,'re':re,'deque':deque,'dataclass':dataclass,'field':field,'Iterator':Iterator}
    definitions('data/original/product/src/dry_lint/functions.py.txt',{'STOP_WORDS','FunctionNode','words','_parse','_call_name','_function_node','_behaviour_nodes','_field_keys','node_tokens'},ns)
    definitions('data/original/product/src/dry_lint/operation_blocks.py.txt',{'_GENERIC','_COMPOUND','_NESTED','_MAX_BLOCKS','_Block','_regions','_blocks'},ns)
    recorded=read('data/selected-original-regions.json');count=0;out=[]
    for case in read('data/recordings.json')['cases']:
        for side in ('new','existing'):
            raw=case['candidate'][side];f=SimpleNamespace(**raw)
            f.analysis=SimpleNamespace(**raw['analysis']) if raw.get('analysis') else None
            blocks=ns['_blocks'](f)
            ident=f.path+'::'+((f.owner+'.') if f.owner else '')+f.name
            expected=recorded.get(ident,[])
            actual=[{'start_line':b.line,'end_line':b.end_line,'kind':b.kind,'counts':dict(Counter(b.tokens)),'ops':sorted(b.operations),'calls':sorted(b.calls)} for b in blocks]
            check(actual==expected,'Frozen region parity: '+ident)
            count+=len(blocks);out.append({'case':case['id'],'side':side,'regions':len(blocks)})
    print(json.dumps({'status':'PASS','original_algorithm':'_blocks/_regions/node_tokens (unchanged ASTs)','functions':len(out),'regions':count,'details':out,'refits':0,'scope':'Native region extraction only; full-background IDF, anchor competition and selector ranking remain recorded, not re-fitted on selected sources.'},indent=2))
if __name__=='__main__':main()
