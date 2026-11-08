"""Optional exact native parser replay. No target functions are executed."""
import ast
import importlib.metadata
import posixpath
import re
import sys
from pathlib import Path
from common import HERE, canonical, digest, read, sha

REQUIREMENTS = {'pydantic':'2.14.2','pydantic-core':'2.50.2','tree-sitter':'0.25.2','tree-sitter-typescript':'0.23.2'}


def dependencies():
    for package, expected in REQUIREMENTS.items():
        try:
            actual=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            raise SystemExit('Native replay requires '+ ' '.join(k+'=='+v for k,v in REQUIREMENTS.items()) +
                             '. Original extraction code and uv.lock are archived; stdlib replay remains available.')
        if actual!=expected:
            raise SystemExit(package+' version mismatch: '+actual+' != '+expected)


def unpack(directory):
    directory=Path(directory)
    archive=read('implementation.json.gz')
    for name,value in archive.items():
        if name.startswith(('src/','scripts/')) or name in ('LICENSE','pyproject.toml','uv.lock'):
            target=directory/name
            if target.exists() and sha(target.read_bytes())!=value['sha256']:
                raise ValueError('Existing implementation changed: '+name)
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():target.write_text(value['text'])
    sys.path.insert(0,str(directory/'src'))
    return archive


def extract(path, text):
    from dry_lint.extractors import PythonExtractor
    from dry_lint.typescript import TypeScriptExtractor
    ex=PythonExtractor() if path.endswith('.py') else TypeScriptExtractor()
    ex.validate_source(path,text)
    functions=ex.functions(path,text)
    for f in functions:f.hash=ex.structure_hash(f)
    return functions


class Source:
    """Read-only adapter to archived public files or caller's immutable Git checkout."""
    def __init__(self, repository=None, revision=None, git_path=None):
        self.data=read('source-files.json.gz')
        self.repository=repository;self.revision=revision;self.git_path=git_path

    def tree(self, repo, pin):
        if repo==self.repository:
            return {x for x in self.git('ls-tree','-r','--name-only',pin).decode().splitlines() if 'enterprise' not in Path(x).parts}
        return {x for x in self.data['trees'][repo] if 'enterprise'not in Path(x).parts}

    def git(self,*args):
        import subprocess
        return subprocess.check_output(['git','--no-replace-objects','-C',str(self.git_path),*args],stderr=subprocess.PIPE)

    def file(self, repo, pin, path):
        if not allowed(path):raise ValueError('Invalid source path')
        if repo==self.repository:return self.git('cat-file','blob',pin+':'+path)
        key=self.data['index'][canonical([repo,pin,path])]
        text=self.data['blobs'][key]['text']
        if sha(text)!=key:raise ValueError('Source hash mismatch')
        return text.encode()

    def resolve_module(self, repo, pin, current, module, level=0):
        if current.endswith('.py'):
            if level:
                base=posixpath.dirname(current).split('/')
                base=base[:len(base)-level+1]
                stem='/'.join(base+module.split('.')) if module else '/'.join(base)
            else:stem=module.replace('.','/')
            options=[stem+'.py',stem+'/__init__.py']
        elif module.startswith('.'):
            stem=posixpath.normpath(posixpath.join(posixpath.dirname(current),module))
            options=[stem]+[stem+s for s in ('.ts','.tsx','/index.ts','/index.tsx')]
            if stem.endswith('.js'):options += [stem[:-3]+'.ts',stem[:-3]+'.tsx']
        else:return None
        found=[x for x in options if x in self.tree(repo,pin) and allowed(x)]
        return found[0] if len(found)==1 else None


def allowed(path):
    return not Path(path).is_absolute() and '..'not in Path(path).parts and 'enterprise'not in Path(path).parts


def anchors_function(archive):
    # Execute only this reviewed recipe function, not lab top-level imports/runner.
    text=archive['lab/trace_followup.py']['text']
    node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='anchors')
    scope=dict(ast=ast,re=re,Path=Path,sha=sha,canonical=canonical,allowed=allowed)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<archived anchors recipe>','exec'),scope)
    return scope['anchors']


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=HERE/'local-native')
    a=p.parse_args()
    dependencies();archive=unpack(a.out);data=read('recordings.json.gz')
    source=Source();extract_count=anchor_count=0;differences=[]
    for case in data['cases']:
        if 'candidate'not in case:continue
        for side in ('new','existing'):
            f=case['candidate'][side];proof=case['native_extraction_proofs'][side]
            raw=source.file(case['repository'],case['revision'],f['path'])
            matches=[n for n in extract(f['path'],raw.decode()) if n.name==f['name'] and n.owner==f['owner'] and n.line==f['line']]
            if len(matches)!=1:raise ValueError('Native symbol ambiguity: '+case['id'])
            native=matches[0].model_dump()
            if proof.get('native_model_dump_sha256') and digest(native)!=proof['native_model_dump_sha256']:raise ValueError('Native extractor mismatch: '+case['id']+':'+side)
            for key in ('code','line','end_line','analysis','bases','declaration'):
                if native[key]!=f[key]:raise ValueError('Native/Candidate mismatch: '+case['id']+':'+key)
            changed=[k for k in f if f[k]!=native.get(k)]
            if 'candidate_fields_differing_from_native'in proof and changed!=proof['candidate_fields_differing_from_native']:raise ValueError('Candidate/native field mismatch')
            if changed:differences.append(dict(id=case['id'],side=side,fields=changed,
                frozen_candidate_hash=f['hash'],reextracted_hash=native['hash'],
                note='Historical native Candidate is preserved exactly; no metadata silently rewritten.'))
            extract_count+=1
            if case['round']=='R1':
                actual=anchors_function(archive)(source,case,side,data['specifications']['R1'])
                expected=next(c for c in data['contexts']['R1'] if c['id']==case['id'])['sides'][side]
                if actual!=expected:raise ValueError('Full source-anchor extraction mismatch: '+case['id'])
                anchor_count+=1
    print(canonical(dict(status='PASS',native_functions=extract_count,full_anchor_recipes=anchor_count,
                         target_code_executed=False,dependencies=REQUIREMENTS,historical_metadata_differences=differences)))

if __name__=='__main__':main()
