#!/usr/bin/env python3
"""Execute the original pure AST operation/signature algorithms on licensed selected files."""
import ast
from collections import Counter
import copy
import hashlib
import json
from types import SimpleNamespace
from reproduce import read

def definitions(text,names,ns):
    nodes=[n for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes}==set(names)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'archived:pure-operation-definitions','exec'),ns)

def run():
    archive=read('data/implementation.json.gz');ns={'ast':ast,'Counter':Counter}
    definitions(archive['lab/measured_contract_tokens.py']['text'],['chain','bindings','Resolver','expr_ok','executable','statement_lists','features','mode'],ns)
    conj={'ast':ast,'copy':copy,'hashlib':hashlib,'json':json,'original':SimpleNamespace(**ns)}
    definitions(archive['lab/funded-rounds/round2/conjunctive.py']['text'],['Abstain','digest','literal_definitions','Normalize','shape','signature','derive'],conj)
    sources=read('data/source-files.json.gz');files={(x['repository'],x['path']):sources['blobs'][x['sha256']]for x in sources['files']};out=[]
    expected=read('data/transform-inputs.json')
    for c in read('data/selected-cases.json.gz'):
        result={}
        for side in ['new','existing']:
            f=c['candidate'][side];tree=ast.parse(files[c['repository'],f['path']]);nodes=[n for n in ast.walk(tree)if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==f['name'] and n.lineno<=f['end_line'] and n.end_lineno>=f['line']]
            assert len(nodes)==1,(c['id'],side)
            tags,regions=ns['features'](tree,nodes[0]);keys,abstentions=conj['derive'](tree,nodes[0],regions)
            want=expected[c['id']][side]
            assert sorted(keys)==want['keys'],(c['id'],side,keys,want)
            result[side]={'generic_tokens':tags,'conjunctive_keys':sorted(keys),'abstentions':abstentions}
        result['shared_exact_keys']=sorted(set(result['new']['conjunctive_keys'])&set(result['existing']['conjunctive_keys']))
        out.append({'id':c['id'],**result})
    return out
if __name__=='__main__':print(json.dumps(run(),indent=2))
