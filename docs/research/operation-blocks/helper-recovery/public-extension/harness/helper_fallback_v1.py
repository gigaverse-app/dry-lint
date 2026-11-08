"""One bounded complete-helper fallback; original winners always take precedence.

Research-only, frozen version 1. Complete body vectors are retrieval evidence only.
Native Function objects remain the sole candidate/judge inputs.
"""
import ast
from collections import defaultdict
from dry_lint import operation_blocks as ob


def helper_block(function):
    python = function.analysis.language == 'python' if function.analysis else function.path.endswith('.py')
    if not python or function.declaration is not None or function.line < 1 or function.end_line < function.line:
        return None
    node = ob._function_node(function.code)
    if node is None:
        return None
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body or any(isinstance(n, ob._NESTED) for s in body for n in ast.walk(s)):
        return None
    start, end = body[0].lineno, body[-1].end_lineno
    nodes = sum(1 for s in body for _ in ob._behaviour_nodes(s))
    if not 4 <= end - start + 1 <= 80 or not 20 <= nodes <= 400:
        return None
    wrapper = ast.FunctionDef(name='', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=body, decorator_list=[])
    tokens = [t for t in ob.node_tokens(wrapper) if not t.startswith('fn:')]
    operations = frozenset(t for t in tokens if t.partition(':')[0] in {'call','attr','key'} and t.partition(':')[2].lower() not in ob._GENERIC)
    calls = frozenset(t for t in operations if t.startswith('call:'))
    if len(set(tokens)) < 8 or len(calls) < 2:
        return None
    return ob._Block(function.line+start-1,function.line+end-1,'whole_helper',tokens,operations,calls)


class HelperFallback:
    name = 'operation-blocks-helper-fallback'
    version = '1'
    similarity_reusable = False
    discovery_unseen = True

    def __init__(self, original):
        self.original = original
        self.functions = original.functions
        self.tfidf = original.tfidf
        self._parents = []
        self.additions = []
        postings = defaultdict(list)
        for i, (f, old) in enumerate(zip(self.functions, original._parents, strict=True)):
            blocks = [ob._Block(b.line,b.end_line,b.kind,b.tokens,b.operations,b.calls,b.vector,b.anchors) for b in old]
            helper = helper_block(f)
            added = helper is not None and not any((b.line,b.end_line)==(helper.line,helper.end_line) for b in blocks)
            if added:
                blocks.append(original._prepare(helper))
            self.additions.append(added)
            self._parents.append(blocks)
            for b in blocks:
                for t in b.anchors:
                    postings[t].append(i)
        # Preserve original region-posting cap semantics in this experiment.
        self._postings = {t:ids for t,ids in postings.items() if len(ids)<=ob._MAX_POSTINGS}
        for blocks in self._parents:
            for b in blocks:
                b.retained = frozenset(t for t in b.anchors if t in self._postings)

    def _query_blocks(self, function):
        i = self.original._positions.get(id(function))
        if i is not None and ob._source_key(function) == self.original._source_keys[i]:
            return self._parents[i]
        blocks = [self.original._prepare(b) for b in ob._blocks(function)]
        helper = helper_block(function)
        if helper and not any((b.line,b.end_line)==(helper.line,helper.end_line) for b in blocks):
            blocks.append(self.original._prepare(helper))
        for b in blocks:
            b.retained=frozenset(t for t in b.anchors if t in self._postings)
        return blocks

    def fallback_ranked(self, function, allowed):
        blocks=self._query_blocks(function)
        pool=ob.OperationBlocksComparer._pool(self,function,blocks)
        full=self.tfidf.vector(function.tokens)
        ranked=[]
        for i in pool:
            f=self.functions[i]
            if not allowed(f):
                continue
            if i not in self.original._full_vectors:
                self.original._full_vectors[i]=self.tfidf.vector(f.tokens)
            fullscore=ob._cosine(full,self.original._full_vectors[i])
            if fullscore<.1:
                continue
            score,shared=ob.OperationBlocksComparer._best(blocks,self._parents[i])
            if score>=.65:
                ranked.append((i,score,shared,fullscore))
        ranked.sort(key=lambda r:(-r[1],self.functions[r[0]].qualname,r[0]))
        seen=set(); result=[]
        for row in ranked:
            key=self.functions[row[0]].qualname
            if key not in seen:
                result.append(row);seen.add(key)
        return result

    def neighbours(self,function,k,allowed):
        if k<=0:
            return []
        original=self.original.neighbours(function,k,allowed)
        if original:
            return original
        return [(self.functions[i],score)for i,score,*_ in self.fallback_ranked(function,allowed)[:k]]
