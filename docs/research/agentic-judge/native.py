#!/usr/bin/env python3
"""Execute the original recorded final-verdict algorithm without harness import side effects."""
import ast
import json
import math
from types import SimpleNamespace
from reproduce import HERE, read, spans, check

def definition(path, name, namespace):
    tree=ast.parse((HERE/path).read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    return namespace[name]

def main():
    # Compile unchanged function ASTs from the readable archived files; never import their top-level adapters.
    ns={'json':json,'math':math}
    parse=definition('data/original/lab/agentic-claude/harness.py.txt','final_decision',ns)
    ns['h']=SimpleNamespace(final_decision=parse)
    strict=definition('data/original/lab/funded-rounds/round1/teacher_v3_adapter.py.txt','strict_submit',ns)
    checked=0
    for c in read('data/recordings.json')['cases']:
        initial=[dict(evidence_id='initial:'+p['side'],start_line=p['line'],end_line=p['end_line']) for p in c['source_proofs']]
        for arm,value,evidence in [('corrected_body',c['corrected_body']['decision'],initial),('teacher',c['teacher_submitted_final'],initial+list(spans(c['observable_tools'])))]:
            source=SimpleNamespace(catalog={e['evidence_id']:e for e in evidence})
            decision,status=strict(value,source)
            check(decision==c[arm]['decision'] and status==c[arm]['status'],'Original strict_submit parity')
            checked+=1
    print(json.dumps({'status':'PASS','original_algorithm':'strict_submit -> final_decision','recorded_finals':checked,'unchanged_function_AST':True,'top_level_harness_imports':0,'provider_calls':0},indent=2))
if __name__=='__main__':main()
