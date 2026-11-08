"""Frozen complete native statement views; retrieval inputs only, never verdict source."""

import ast
import hashlib
import textwrap


class StatementViews:
    """Clone the validated encoder tokenizer without its inference truncation/padding."""

    version = "1-native-lines-max2-wp48-180-identity256-prefix254-containment-size-line"

    def __init__(self, encoder):
        self.tokenizer = type(encoder.tokenizer).from_str(encoder.tokenizer.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()

    def token_count(self, s):
        return len(self.tokenizer.encode(s).ids)

    def prefix_end(self, code):
        e = self.tokenizer.encode(code)
        return e.offsets[min(254, len(e.offsets) - 2)][1]

    def statements(self, f):
        """Return complete native line spans, recursively descending oversized statements."""
        lines = f.code.splitlines(keepends=True)
        spans = []
        if f.path.endswith(".py"):
            try:
                tree = ast.parse(textwrap.dedent(f.code))
            except SyntaxError:
                return [], "python-parse-unavailable"
            for n in ast.walk(tree):
                if isinstance(n, ast.stmt) and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                        continue
                    a = n.lineno - 1
                    b = n.end_lineno
                    code = "".join(lines[a:b]).rstrip("\n")
                    count = self.token_count(code)
                    if 48 <= count <= 180:
                        spans.append((a, b, code, count))
        else:
            import tree_sitter_typescript
            from tree_sitter import Language, Parser

            parser = Parser(
                Language(
                    tree_sitter_typescript.language_tsx()
                    if f.path.endswith(".tsx")
                    else tree_sitter_typescript.language_typescript()
                )
            )
            tree = parser.parse(f.code.encode())
            stack = [tree.root_node]
            while stack:
                n = stack.pop()
                stack.extend(reversed(n.named_children))
                if n.type.endswith("_statement") or n.type in {"lexical_declaration", "variable_declaration"}:
                    a = n.start_point.row
                    b = n.end_point.row + 1
                    code = "".join(lines[a:b]).rstrip("\n")
                    count = self.token_count(code)
                    if 48 <= count <= 180:
                        spans.append((a, b, code, count))
        # Exclude overlaps: larger complete operation dominates child statements.
        unique = sorted(set(spans), key=lambda s: (s[0], -(s[1] - s[0])))
        kept = []
        for s in unique:
            if not any(s[0] >= t[0] and s[1] <= t[1] for t in kept):
                kept.append(s)
        return kept, "ok"

    def views(self, f):
        if self.token_count(f.code) <= 256:
            return [], "untruncated"
        spans, status = self.statements(f)
        cut = self.prefix_end(f.code)
        lines = f.code.splitlines(keepends=True)
        spans = [s for s in spans if len("".join(lines[: s[1]])) > cut]
        # Two largest disjoint operations; equal sizes keep the earliest source line.
        spans.sort(key=lambda s: (-s[3], s[0]))
        chosen = []
        for s in spans:
            if not any(s[0] < t[1] and t[0] < s[1] for t in chosen):
                chosen.append(s)
            if len(chosen) == 2:
                break
        result = []
        for a, b, code, count in sorted(chosen):
            # Identity is kept explicit; an overlong identity is excluded, never silently truncated.
            identity = f.name
            text = identity + "\n" + code
            if self.token_count(text) > 256:
                continue
            result.append(
                {
                    "text": text,
                    "kind": "complete-statement-native-lines",
                    "relative_line": a + 1,
                    "relative_end_line": b,
                    "absolute_line": f.line + a,
                    "absolute_end_line": f.line + b - 1,
                    "operation_wordpieces": count,
                    "input_wordpieces": self.token_count(text),
                    "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "function_body_sha256": hashlib.sha256(f.code.encode()).hexdigest(),
                    "function_id": f.qualname,
                    "identity_prefix": identity,
                    "tail_beyond_prefix": True,
                }
            )
        return result, status
