"""Source-exact, bounded complete statement views; no labels or generated summaries."""
import ast
import textwrap
from common import *
from tokenizers import Tokenizer
TOK=Tokenizer.from_file(str(OLD/'model-cache/tokenizer.json'))
TOK.no_truncation();TOK.no_padding()
def token_count(s):return len(TOK.encode(s).ids)
def prefix_end(code):
    e=TOK.encode(code);return e.offsets[min(254,len(e.offsets)-2)][1]
def statements(f):
    """Return complete native line spans, recursively descending oversized statements."""
    lines=f.code.splitlines(keepends=True)
    spans=[]
    if f.path.endswith('.py'):
        try:tree=ast.parse(textwrap.dedent(f.code))
        except SyntaxError:return [],'python-parse-unavailable'
        for n in ast.walk(tree):
            if isinstance(n,ast.stmt) and not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                if isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):continue
                a=n.lineno-1;b=n.end_lineno
                code=''.join(lines[a:b]).rstrip('\n')
                count=token_count(code)
                if 48<=count<=180:spans.append((a,b,code,count))
    else:
        from tree_sitter import Language,Parser
        import tree_sitter_typescript
        parser=Parser(Language(tree_sitter_typescript.language_tsx() if f.path.endswith('.tsx') else tree_sitter_typescript.language_typescript()))
        tree=parser.parse(f.code.encode());stack=[tree.root_node]
        while stack:
            n=stack.pop();stack.extend(reversed(n.named_children))
            if n.type.endswith('_statement') or n.type in {'lexical_declaration','variable_declaration'}:
                a=n.start_point.row;b=n.end_point.row+1
                code=''.join(lines[a:b]).rstrip('\n');count=token_count(code)
                if 48<=count<=180:spans.append((a,b,code,count))
    # Exclude overlaps: larger complete operation dominates child statements.
    unique=sorted(set(spans),key=lambda s:(s[0],-(s[1]-s[0])))
    kept=[]
    for s in unique:
        if not any(s[0]>=t[0] and s[1]<=t[1] for t in kept):kept.append(s)
    return kept,'ok'
def views(f):
    if token_count(f.code)<=256:return [],'untruncated'
    spans,status=statements(f);cut=prefix_end(f.code)
    lines=f.code.splitlines(keepends=True)
    spans=[s for s in spans if len(''.join(lines[:s[1]]))>cut]
    # Largest tail operation then farthest disjoint operation; no label-adaptive placement.
    spans.sort(key=lambda s:(-s[3],s[0]))
    chosen=[]
    for s in spans:
        if not any(s[0]<t[1] and t[0]<s[1] for t in chosen):chosen.append(s)
        if len(chosen)==2:break
    result=[]
    for a,b,code,count in sorted(chosen):
        # Identity is kept explicit; an overlong identity is excluded, never silently truncated.
        identity=f.name
        text=identity+'\n'+code
        if token_count(text)>256:continue
        result.append({'text':text,'kind':'complete-statement-native-lines','relative_line':a+1,'relative_end_line':b,
                       'absolute_line':f.line+a,'absolute_end_line':f.line+b-1,'operation_wordpieces':count,
                       'input_wordpieces':token_count(text),'input_sha256':sha(text.encode()),
                       'function_body_sha256':sha(f.code.encode()),'function_id':f.qualname,
                       'identity_prefix':identity,'tail_beyond_prefix':True})
    return result,status
