#!/usr/bin/env python3
"""Run the original centered-window inventory method on three pinned associations."""
import ast,collections,hashlib,json,re,tempfile
from pathlib import Path
from types import SimpleNamespace
from reproduce import HERE,read

def run():
    archive=read('data/implementation.json.gz');fixture=read('data/linked-window-inputs.json');sources=read('data/source-files.json.gz')
    files={f['path']:sources['blobs'][f['sha256']]for f in sources['files']if f['repository']==fixture['repository']}
    ns={'re':re};tree=ast.parse(archive['src/dry_lint/functions.py']['text'])
    defs=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='words' or isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='STOP_WORDS'for t in n.targets)]
    exec(compile(ast.Module(body=defs,type_ignores=[]),'archived:word splitting','exec'),ns)
    frozen={'re':re};tree=ast.parse(archive['lab/linked_docs.py']['text'])
    defs=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='paragraphs' or isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id in {'LINK','INLINE'}for t in n.targets)]
    exec(compile(ast.Module(body=defs,type_ignores=[]),'archived:paragraph selection','exec'),frozen)
    cls=next(n for n in ast.parse(archive['lab/funded-rounds/evaluate_round2.py']['text']).body if isinstance(n,ast.ClassDef)and n.name=='AnchorWindowSnapshot')
    outputs={}
    with tempfile.TemporaryDirectory(prefix='local-window-',dir=HERE) as temporary:
        base=Path(temporary);old=base/'cohorts'/fixture['key']/'litellm';old.mkdir(parents=True);out=base/'out';out.mkdir()
        (old/'associations.jsonl').write_text(''.join(json.dumps(x)+'\n'for x in fixture['associations']))
        (old/'coverage.json').write_text('{}')
        for name in ['markdown-manifest.jsonl','link-inventory.jsonl']:(old/name).write_text('')
        sha=lambda b:hashlib.sha256(b).hexdigest()
        runner=SimpleNamespace(rows=lambda p:[json.loads(s)for s in p.read_text().splitlines()],sha=sha,frozen=SimpleNamespace(**frozen),jsonl=lambda p,rs:outputs.update({p.name:rs}))
        env={'collections':collections,'json':json,'re':re,'OLD':base,'run':runner,'shared_adapter':SimpleNamespace(Snapshot=object),'words':ns['words'],'prereg_hash':sha(archive['lab/funded-rounds/round2/PREREGISTRATION.json']['text'].encode())}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'archived:AnchorWindowSnapshot','exec'),env)
        snapshot=env['AnchorWindowSnapshot']();snapshot.key=fixture['key'];snapshot.bg=SimpleNamespace(repository=fixture['repository'],documents={a['position']:SimpleNamespace(id=a['owner'])for a in fixture['associations']});snapshot.root=out;snapshot.source=lambda p:files[p];snapshot.index=SimpleNamespace(idf=dict.fromkeys(fixture['retained_word_membership'],1))
        snapshot.inventory()
    audits=outputs['associations.jsonl'];expected=fixture['expected_associations']
    for got,want in zip(audits,expected):
        for key in ['owner','reference','anchor_start','window_start','previous_anchor_in_window','passage','bounded_terms']:
            assert got[key]==want[key],(key,got['owner'])
    return {'scope':fixture['scope'],'replayed_associations':[{'owner':a['owner'],'anchor_start':a['anchor_start'],'before_contains_reference':a['previous_anchor_in_window'],'after_contains_reference':a['reference'] in a['passage'],'after_word_count':len(a['bounded_terms'])}for a in audits]}
if __name__=='__main__':print(json.dumps(run(),indent=2))
