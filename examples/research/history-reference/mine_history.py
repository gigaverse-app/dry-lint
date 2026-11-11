"""Mine git history for commits where maintainers removed duplicated Python functions.

Stdlib only. Run ``python mine_history.py --help``; README.md has the case definitions.

Stages (each reads the previous stage's files in ``--out``):

- ``log``     list the newest non-merge commits touching ``.py`` files, with blob ids (needs no blobs)
- ``fetch``   batch-fetch the blobs those commits need into a ``--filter=blob:none`` clone, watching free disk
- ``mine``    parse before/after versions and emit every candidate with its features, no similarity thresholds
- ``select``  apply the thresholds, de-duplicate, and write ``cases-<repo>.jsonl`` plus a summary
- ``sample``  draw a fixed-seed stratified sample of cases and print them for reading
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import io
import json
import keyword
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ZERO = "0" * 40
KEYWORDS = re.compile(
    r"dedup|de-dup|duplicat|consolidat|\bdry\b|refactor|extract|reuse|re-use|shared helper|use existing|"
    r"common helper|unify|single source",
    re.IGNORECASE,
)
TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
VENDORED_PATH = re.compile(
    r"(^|/)(vendor|vendored|third_party|_vendor|site-packages|node_modules|\.venv|migrations|generated)/"
    r"|_pb2(_grpc)?\.py$|(^|/)setup\.py$"
)
IDENT = re.compile(r"[A-Za-z_]\w*")
TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|\S")
# Identifiers too common to say anything about shared logic.
STOP = set(keyword.kwlist) | {"self", "cls", "None", "True", "False", "str", "int", "dict", "list", "len", "isinstance"}

MIN_STATEMENTS = 3
MOVED_RATIO = 0.8
MEGA_COMMIT_FILES = 80


# ---------------------------------------------------------------- git access


class Git:
    """One repository; blob reads never trigger a lazy fetch, so a missing blob is counted, not fetched."""

    def __init__(self, repo: Path):
        self.repo = repo
        env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
        self.env = env
        self.proc = subprocess.Popen(
            ["git", "-C", str(repo), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self.missing: set[str] = set()
        self._trees: dict[str, dict[str, str]] = {}
        self._modules: dict[tuple[str, str], Module | None] = {}

    def run(self, *args: str, stdin: bytes | None = None) -> str:
        out = subprocess.run(
            ["git", "-C", str(self.repo), *args], input=stdin, capture_output=True, env=self.env, check=True
        )
        return out.stdout.decode("utf-8", errors="replace")

    def blob(self, oid: str) -> str | None:
        if oid == ZERO:
            return None
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(oid.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().decode()
        if header.endswith("missing\n"):
            self.missing.add(oid)
            return None
        size = int(header.split()[2])
        data = self.proc.stdout.read(size)
        self.proc.stdout.read(1)
        return data.decode("utf-8", errors="replace")

    def module(self, oid: str, path: str, stats: Counter) -> Module | None:
        """The parsed blob, cached: a file's new version in one commit is its old version in the next."""
        key = (oid, path)
        if key in self._modules:
            self._modules[key] = self._modules.pop(key)  # most recently used goes last
            return self._modules[key]
        src = self.blob(oid)
        if src is None:
            stats["blob_missing"] += 1
            return None
        parsed = parse_module(path, src)
        if parsed is None:
            stats["parse_failed"] += 1
        self._modules[key] = parsed
        if len(self._modules) > 400:
            self._modules.pop(next(iter(self._modules)))
        return parsed

    def py_tree(self, rev: str) -> dict[str, str]:
        """All .py paths at ``rev`` mapped to blob ids (trees only, no blobs)."""
        if rev not in self._trees:
            if len(self._trees) > 64:
                self._trees.clear()
            listing = self.run("ls-tree", "-r", "--full-tree", rev)
            tree = {}
            for line in listing.splitlines():
                meta, path = line.split("\t", 1)
                if path.endswith(".py"):
                    tree[path] = meta.split()[2]
            self._trees[rev] = tree
        return self._trees[rev]


# ---------------------------------------------------------------- stage: log


RAW_LINE = re.compile(r":\d{6} \d{6} [0-9a-f]{40} [0-9a-f]{40} [A-Z]\d*\t")


def parse_raw_log(text: str) -> list[dict]:
    commits = []
    for chunk in text.split("\x01")[1:]:
        header, _, raw = chunk.partition("\x03")
        head = header.split("\x02")
        shas = head[0].split()
        files = []
        for line in raw.splitlines():
            if not RAW_LINE.match(line):
                continue
            meta, path = line.split("\t", 1)
            parts = meta.split()
            files.append({"old": parts[2], "new": parts[3], "status": parts[4], "path": path})
        commits.append(
            {
                "commit": shas[0],
                "parents": shas[1:],
                "date": head[1],
                "subject": head[2],
                "body": "\x02".join(head[3:]),
                "files": files,
            }
        )
    return commits


def cmd_log(args: argparse.Namespace) -> None:
    git = Git(args.repo)
    raw = git.run(
        "-c",
        "core.quotepath=off",
        "log",
        "--no-merges",
        f"-n{args.commits}",
        "--format=%x01%H %P%x02%aI%x02%s%x02%b%x03",
        "--raw",
        "--no-renames",
        "--no-abbrev",
        args.rev,
        "--",
        "*.py",
    )
    commits = parse_raw_log(raw)
    head = git.run("rev-parse", args.rev).strip()
    path = args.out / f"commits-{args.name}.json"
    path.write_text(json.dumps({"repo": args.name, "head": head, "commits": commits}), encoding="utf-8")
    print(f"{len(commits)} commits, {commits[-1]['date']} .. {commits[0]['date']} -> {path}")


def wanted_files(commit: dict) -> list[dict]:
    return [f for f in commit["files"] if not VENDORED_PATH.search(f["path"])]


def is_mega(commit: dict) -> bool:
    return len([f for f in wanted_files(commit) if not TEST_PATH.search(f["path"])]) > MEGA_COMMIT_FILES


def is_candidate_commit(commit: dict) -> bool:
    """Every case kind needs a modified file (a caller or a shrinking site survives the commit)."""
    if len(commit["parents"]) != 1 or is_mega(commit):
        return False
    return any(f["status"] == "M" for f in wanted_files(commit))


# ---------------------------------------------------------------- stage: fetch


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def cmd_fetch(args: argparse.Namespace) -> None:
    git = Git(args.repo)
    if args.oids:
        oids = [o for o in args.oids.read_text().split() if o]
    else:
        data = json.loads((args.out / f"commits-{args.name}.json").read_text(encoding="utf-8"))
        oids = []
        for commit in data["commits"]:
            if not is_candidate_commit(commit):
                continue
            for f in wanted_files(commit):
                if args.skip_tests and TEST_PATH.search(f["path"]):
                    continue
                oids += [o for o in (f["old"], f["new"]) if o != ZERO]
    oids = list(dict.fromkeys(oids))
    check = subprocess.run(
        ["git", "-C", str(args.repo), "cat-file", "--batch-check"],
        input="\n".join(oids).encode() + b"\n",
        capture_output=True,
        env=git.env,
        check=True,
    ).stdout.decode()
    missing = [line.split()[0] for line in check.splitlines() if line.endswith(" missing")]
    print(f"{len(oids)} blobs wanted, {len(missing)} missing, {free_gb(args.repo):.2f} GB free", flush=True)
    for start in range(0, len(missing), args.batch):
        if free_gb(args.repo) < args.floor_gb:
            print(f"stopping: free space below {args.floor_gb} GB after {start} blobs", flush=True)
            sys.exit(2)
        batch = missing[start : start + args.batch]
        subprocess.run(
            [
                "git",
                "-C",
                str(args.repo),
                "-c",
                "gc.auto=0",
                "-c",
                "fetch.negotiationAlgorithm=noop",
                "fetch",
                "origin",
                "--no-tags",
                "--no-write-fetch-head",
                "--recurse-submodules=no",
                "--filter=blob:none",
                "--stdin",
            ],
            input="\n".join(batch).encode() + b"\n",
            capture_output=True,
            check=True,
        )
        print(f"fetched {start + len(batch)}/{len(missing)}, {free_gb(args.repo):.2f} GB free", flush=True)


# ---------------------------------------------------------------- python parsing


@dataclass
class Func:
    path: str
    qualname: str
    name: str
    cls: str | None  # qualname of the directly enclosing class, if a method
    start: int
    end: int
    code: str
    own_lines: list[str]  # stripped non-blank, non-comment lines, excluding nested defs and the docstring
    statements: int
    calls: list[tuple]  # call references, see call_ref()
    tokens: list[str] = field(default_factory=list)
    idents: set[str] = field(default_factory=set)


@dataclass
class Module:
    path: str
    funcs: dict[str, Func]
    ambiguous: set[str]
    top_level: set[str]
    from_imports: dict[str, tuple[int, str, str]]  # local name -> (level, module, original name)
    module_imports: dict[str, tuple[int, str]]  # local alias -> (level, dotted module)


def call_ref(node: ast.Call) -> tuple | None:
    func = node.func
    if isinstance(func, ast.Name):
        return ("name", func.id)
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name) and base.id in ("self", "cls"):
            return ("self", func.attr)
        dotted = []
        while isinstance(base, ast.Attribute):
            dotted.append(base.attr)
            base = base.value
        if isinstance(base, ast.Name):
            dotted.append(base.id)
            return ("mod", ".".join(reversed(dotted)), func.attr)
    return None


def strip_comment(line: str) -> str:
    return line.split("#", 1)[0].strip() if "#" in line and "'" not in line and '"' not in line else line.strip()


STMT_FIELDS = ("body", "orelse", "finalbody", "handlers", "cases")
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def child_statements(stmt: ast.AST) -> list[ast.AST]:
    """Statements nested directly in a compound statement (through except handlers and match cases)."""
    out: list[ast.AST] = []
    for name in STMT_FIELDS:
        for item in getattr(stmt, name, None) or []:
            if isinstance(item, ast.stmt):
                out.append(item)
            else:  # ExceptHandler, match_case
                out += item.body
    return out


def expressions(stmt: ast.AST) -> list[ast.AST]:
    """The expression parts of a statement, without its nested statements."""
    out: list[ast.AST] = []
    for name, value in ast.iter_fields(stmt):
        if name in STMT_FIELDS:
            for item in value or []:
                if not isinstance(item, ast.stmt):  # ExceptHandler.type, match_case.guard
                    out += [getattr(item, "type", None), getattr(item, "guard", None)]
            continue
        if isinstance(value, ast.AST):
            out.append(value)
        elif isinstance(value, list):
            out += [v for v in value if isinstance(v, ast.AST)]
    return [e for e in out if e is not None]


def parse_module(path: str, source: str) -> Module | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # old invalid escapes in historical files
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    lines = source.splitlines()
    funcs: dict[str, Func] = {}
    ambiguous: set[str] = set()
    top_level: set[str] = set()
    from_imports: dict[str, tuple[int, str, str]] = {}
    module_imports: dict[str, tuple[int, str]] = {}

    def visit(stmts: list[ast.AST], prefix: str, cls: str | None, depth: int) -> None:
        for node in stmts:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    from_imports[alias.asname or alias.name] = (node.level, node.module or "", alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    # `import a.b` binds `a`, and `a.b.f()` reaches through it.
                    module_imports[alias.asname or alias.name] = (0, alias.name)
            elif isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.", f"{prefix}{node.name}", depth + 1)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                qual = f"{prefix}{node.name}"
                if depth == 0:
                    top_level.add(node.name)
                if qual in funcs:
                    ambiguous.add(qual)
                funcs[qual] = make_func(path, node, qual, cls, lines)
                visit(node.body, f"{qual}.", None, depth + 1)
            else:
                # defs under `if`/`try` at module or class level keep the enclosing prefix
                visit(child_statements(node), prefix, cls, depth)

    visit(tree.body, "", None, 0)
    for qual in ambiguous:
        funcs.pop(qual, None)
    return Module(path, funcs, ambiguous, top_level, from_imports, module_imports)


def make_func(path: str, node: ast.FunctionDef | ast.AsyncFunctionDef, qual: str, cls: str | None, lines: list[str]):
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    end = node.end_lineno or node.lineno
    excluded: set[int] = set()
    calls: list[tuple] = []
    statements = 0
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            excluded.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
            body = body[1:]
    # Count statements and collect calls, leaving nested functions and classes to themselves.
    stack = body
    while stack:
        stmt = stack.pop()
        if isinstance(stmt, DEFS):
            first = min([stmt.lineno] + [d.lineno for d in stmt.decorator_list])
            excluded.update(range(first, (stmt.end_lineno or stmt.lineno) + 1))
            continue
        statements += 1
        for expr in expressions(stmt):
            for sub in ast.walk(expr):
                if isinstance(sub, ast.Call):
                    ref = call_ref(sub)
                    if ref:
                        calls.append(ref)
        stack += child_statements(stmt)
    body_start = node.body[0].lineno if node.body else node.lineno
    own = []
    for no in range(body_start, end + 1):
        if no in excluded:
            continue
        text = strip_comment(lines[no - 1]) if no - 1 < len(lines) else ""
        if text and not text.startswith("#"):
            own.append(text)
    code = "\n".join(lines[start - 1 : end])
    func = Func(path, qual, node.name, cls, start, end, code, own, statements, calls)
    func.tokens = TOKEN.findall("\n".join(own))
    func.idents = ident_set(func.tokens)
    return func


# ---------------------------------------------------------------- similarity


def ident_set(text_or_tokens) -> set[str]:
    tokens = TOKEN.findall(text_or_tokens) if isinstance(text_or_tokens, str) else text_or_tokens
    return {t for t in tokens if IDENT.fullmatch(t) and t not in STOP}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def containment(part: set, whole: set) -> float:
    """Share of ``whole``'s identifiers that also occur in ``part``."""
    return len(part & whole) / len(whole) if whole else 0.0


def seq_ratio(a: list[str], b: list[str]) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def near_identical(a: Func, others: list[Func]) -> Func | None:
    """The function in ``others`` whose body is the same as ``a``'s up to small edits (a move or rename)."""
    sa = a.idents
    best, best_ratio = None, 0.0
    for b in others:
        n, m = len(a.tokens), len(b.tokens)
        if not n or not m or min(n, m) / max(n, m) < 0.6:
            continue
        if jaccard(sa, b.idents) < 0.5:
            continue
        sm = difflib.SequenceMatcher(None, a.tokens, b.tokens, autojunk=False)
        if sm.quick_ratio() < MOVED_RATIO:
            continue
        ratio = sm.ratio()
        if ratio >= MOVED_RATIO and ratio > best_ratio:
            best, best_ratio = b, ratio
    return best


def line_diff(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    removed, added = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += before[i1:i2]
        if tag in ("replace", "insert"):
            added += after[j1:j2]
    return removed, added


# ---------------------------------------------------------------- name resolution


def resolve_module(level: int, dotted: str, cur_path: str, pyset: dict[str, str], cache: dict) -> str | None:
    key = (level, dotted, cur_path if level else "")
    if key in cache:
        return cache[key]
    result = None
    rel = dotted.replace(".", "/") if dotted else ""
    if level:
        base = cur_path.split("/")[:-1]
        base = base[: len(base) - (level - 1)] if level > 1 else base
        stem = "/".join([*base, rel] if rel else base)
        for cand in (f"{stem}.py", f"{stem}/__init__.py"):
            if cand.lstrip("/") in pyset:
                result = cand.lstrip("/")
                break
    elif rel:
        for cand in (f"{rel}.py", f"{rel}/__init__.py"):
            if cand in pyset:
                result = cand
                break
        if result is None and "." in dotted:
            # a package under a source root, e.g. `enterprise/litellm_enterprise/...`; one-part names are
            # left alone so that `import json` never resolves to some `pkg/json.py`
            hits = [p for p in pyset if p.endswith(f"/{rel}.py") or p.endswith(f"/{rel}/__init__.py")]
            if hits:
                result = min(hits, key=len)
    cache[key] = result
    return result


def resolve_call(ref: tuple, caller: Func, mod: Module, pyset: dict[str, str], cache: dict) -> tuple[str, str] | None:
    """(path, qualname) the call reference names, or None when it cannot be resolved statically."""
    kind = ref[0]
    if kind == "name":
        name = ref[1]
        if name in mod.top_level and name in mod.funcs:
            return (mod.path, name)
        if name in mod.from_imports:
            level, module, orig = mod.from_imports[name]
            target = resolve_module(level, module, mod.path, pyset, cache)
            if target:
                return (target, orig)
        return None
    if kind == "self":
        if caller.cls and f"{caller.cls}.{ref[1]}" in mod.funcs:
            return (mod.path, f"{caller.cls}.{ref[1]}")
        return None
    if kind == "mod":
        dotted, name = ref[1], ref[2]
        head = dotted.split(".")[0]
        if dotted in mod.module_imports:
            level, module = mod.module_imports[dotted]
        elif head in mod.module_imports and mod.module_imports[head][1] == head:
            level, module = 0, dotted
        elif dotted in mod.from_imports:
            # `from pkg import module` then `module.f()`
            level, base, orig = mod.from_imports[dotted]
            level, module = level, f"{base}.{orig}" if base else orig
        else:
            return None
        target = resolve_module(level, module, mod.path, pyset, cache)
        if target:
            return (target, name)
    return None


# ---------------------------------------------------------------- stage: mine


class CommitView:
    """Parsed before/after versions of one commit's files, plus lazy access to other files at the parent."""

    def __init__(self, git: Git, commit: dict, stats: Counter):
        self.git = git
        self.commit = commit
        self.parent = commit["parents"][0]
        self.stats = stats
        self.before: dict[str, Module] = {}
        self.after: dict[str, Module] = {}
        self.status: dict[str, str] = {}
        self._extra: dict[str, Module | None] = {}
        self.cache_p: dict = {}
        self.cache_c: dict = {}
        for f in wanted_files(commit):
            self.status[f["path"]] = f["status"]
            for oid, side in ((f["old"], self.before), (f["new"], self.after)):
                if oid == ZERO:
                    continue
                parsed = git.module(oid, f["path"], stats)
                if parsed is not None:
                    side[f["path"]] = parsed

    def pyset_p(self) -> dict[str, str]:
        return self.git.py_tree(self.parent)

    def pyset_c(self) -> dict[str, str]:
        return self.git.py_tree(self.commit["commit"])

    def module_at_parent(self, path: str) -> Module | None:
        if path in self.before:
            return self.before[path]
        if path not in self._extra:
            oid = self.pyset_p().get(path)
            self._extra[path] = self.git.module(oid, path, self.stats) if oid else None
        return self._extra[path]

    def func_at_parent(self, path: str, qual: str, follow: bool = True) -> Func | None:
        mod = self.module_at_parent(path)
        if mod is None:
            return None
        if qual in mod.funcs:
            return mod.funcs[qual]
        if follow and "." not in qual and qual in mod.from_imports:
            # one hop through a re-export, e.g. a package __init__
            level, module, orig = mod.from_imports[qual]
            target = resolve_module(level, module, path, self.pyset_p(), self.cache_p)
            if target and target != path:
                return self.func_at_parent(target, orig, follow=False)
        return None


def member(func: Func, rev: str, removed: list[str] | None = None) -> dict:
    out = {
        "path": func.path,
        "qualname": func.qualname,
        "rev": rev,
        "start_line": func.start,
        "end_line": func.end,
        "statements": func.statements,
        "code": func.code,
    }
    if removed is not None:
        out["removed_lines"] = removed
    return out


def is_test(path: str) -> bool:
    return bool(TEST_PATH.search(path))


def mine_commit(git: Git, commit: dict, stats: Counter) -> list[dict]:
    view = CommitView(git, commit, stats)
    sha, parent = commit["commit"], view.parent
    after_funcs = [f for m in view.after.values() for f in m.funcs.values()]
    before_funcs = [f for m in view.before.values() for f in m.funcs.values()]
    base = {
        "commit": sha,
        "parent": parent,
        "date": commit["date"],
        "message": commit["subject"],
        "keyword_signal": bool(KEYWORDS.search(commit["subject"] + "\n" + commit.get("body", ""))),
    }
    cases: list[dict] = []

    # Functions that survive in a modified file: (path, qual) -> (before, after, removed, added)
    survivors: dict[tuple[str, str], tuple[Func, Func, list[str], list[str]]] = {}
    for path, mod_c in view.after.items():
        mod_p = view.before.get(path)
        if mod_p is None:
            continue
        for qual, fc in mod_c.funcs.items():
            fp = mod_p.funcs.get(qual)
            if fp is None:
                continue
            if fp.own_lines == fc.own_lines and fp.calls == fc.calls:
                continue
            removed, added = line_diff(fp.own_lines, fc.own_lines)
            survivors[(path, qual)] = (fp, fc, removed, added)

    memo: dict[tuple, dict] = {}

    def resolved(func: Func, mod: Module, side: str) -> dict[tuple[str, str], tuple]:
        key = (side, func.path, func.qualname)
        if key not in memo:
            pyset, cache = (view.pyset_p(), view.cache_p) if side == "p" else (view.pyset_c(), view.cache_c)
            out: dict[tuple[str, str], tuple] = {}
            for ref in func.calls:
                target = resolve_call(ref, func, mod, pyset, cache)
                if target:
                    out.setdefault(target, ref)
            memo[key] = out
        return memo[key]

    def new_calls(fp: Func, fc: Func) -> dict[tuple[str, str], tuple]:
        """Calls ``fc`` makes, resolved at the commit, that ``fp`` did not make at the parent."""
        before = resolved(fp, view.before[fp.path], "p")
        after = resolved(fc, view.after[fc.path], "c")
        if ("new", fc.path, fc.qualname) not in memo:
            old_refs = set(fp.calls)
            unresolved = {r for r in fc.calls if r not in old_refs} - set(after.values())
            stats["new_call_unresolved"] += len(unresolved)
            memo[("new", fc.path, fc.qualname)] = {}
        return {t: r for t, r in after.items() if t not in before}

    # ---- pair-delete
    removed_funcs = []
    for path, mod_p in view.before.items():
        mod_c = view.after.get(path)
        for qual, fp in mod_p.funcs.items():
            if mod_c is not None and (qual in mod_c.funcs or qual in mod_c.ambiguous):
                continue
            removed_funcs.append(fp)
    for a in removed_funcs:
        if a.statements < MIN_STATEMENTS:
            stats["delete_small_A"] += 1
            continue
        moved = near_identical(a, after_funcs)
        if moved is not None:
            stats["delete_moved"] += 1
            continue
        redirected: dict[tuple[str, str], list[str]] = defaultdict(list)
        for (path, qual), (fp, fc, _removed, _added) in survivors.items():
            if a.name not in {r[-1] for r in fp.calls}:
                continue
            calls_a = resolved(fp, view.before[path], "p")
            if (a.path, a.qualname) not in calls_a:
                continue
            for target in new_calls(fp, fc):
                redirected[target].append(f"{path}::{qual}")
        for (bpath, bqual), callers in redirected.items():
            if (bpath, bqual) == (a.path, a.qualname):
                continue
            b = view.func_at_parent(bpath, bqual)
            if b is None:
                stats["delete_B_not_at_parent"] += 1
                continue
            if b.statements < MIN_STATEMENTS:
                stats["delete_small_B"] += 1
                continue
            sa, sb = ident_set(a.tokens), ident_set(b.tokens)
            a_calls = {r[-1] for r in a.calls}
            cases.append(
                {
                    **base,
                    "kind": "pair-delete",
                    "members": [member(a, parent), member(b, parent)],
                    "callers": callers,
                    "features": {
                        "jaccard": round(jaccard(sa, sb), 3),
                        "seq_ratio": round(seq_ratio(a.tokens, b.tokens), 3),
                        "a_calls_b": b.name in a_calls,
                        "same_name": a.name == b.name,
                        "a_lines": len(a.own_lines),
                        "b_lines": len(b.own_lines),
                    },
                }
            )

    # ---- pair-shrink and family
    new_helpers: dict[tuple[str, str], Func] = {}
    before_keys = {(f.path, f.qualname) for f in before_funcs}
    for path, mod_c in view.after.items():
        mod_p = view.before.get(path)
        for qual, fc in mod_c.funcs.items():
            if mod_p is not None and qual in mod_p.funcs:
                continue
            if (path, qual) in before_keys:
                continue
            new_helpers[(path, qual)] = fc

    sites_for_helper: dict[tuple[str, str], list] = defaultdict(list)
    for (path, qual), (fp, fc, removed, added) in survivors.items():
        if len(removed) < 3 or len(removed) <= len(added):
            continue
        gained = new_calls(fp, fc)
        for target in gained:
            if target in new_helpers:
                sites_for_helper[target].append((fp, fc, removed, added))
                continue
            if len(removed) < 5 or target == (path, qual):
                continue
            b = view.func_at_parent(*target)
            if b is None:
                stats["shrink_B_not_at_parent"] += 1
                continue
            if b.statements < MIN_STATEMENTS or fp.statements < MIN_STATEMENTS:
                stats["shrink_small"] += 1
                continue
            if b.path in view.after and b.qualname not in view.after[b.path].funcs:
                stats["shrink_B_removed"] += 1
                continue
            rem_set, b_set = ident_set("\n".join(removed)), ident_set(b.tokens)
            rem_tokens = TOKEN.findall("\n".join(removed))
            cases.append(
                {
                    **base,
                    "kind": "pair-shrink",
                    "members": [member(fp, parent, removed), member(b, parent)],
                    "features": {
                        "jaccard": round(jaccard(rem_set, b_set), 3),
                        "containment": round(containment(rem_set, b_set), 3),
                        "seq_ratio": round(seq_ratio(rem_tokens, b.tokens), 3),
                        "removed": len(removed),
                        "added": len(added),
                        "b_lines": len(b.own_lines),
                    },
                }
            )

    for key, sites in sites_for_helper.items():
        if len(sites) < 2:
            continue
        h = new_helpers[key]
        if h.statements < MIN_STATEMENTS:
            stats["family_small_H"] += 1
            continue
        if near_identical(h, before_funcs) is not None:
            stats["family_H_moved"] += 1
            continue
        sites = [s for s in sites if s[0].statements >= MIN_STATEMENTS]
        if len(sites) < 2:
            stats["family_small_sites"] += 1
            continue
        h_set = ident_set(h.tokens)
        rem_sets = [ident_set("\n".join(s[2])) for s in sites]
        site_sims = [round(jaccard(r, h_set), 3) for r in rem_sets]
        pairwise = [round(jaccard(rem_sets[i], rem_sets[j]), 3) for i in range(len(sites)) for j in range(i)]
        cases.append(
            {
                **base,
                "kind": "family",
                "members": [member(s[0], parent, s[2]) for s in sites],
                "helper": member(h, sha),
                "features": {
                    "sites": len(sites),
                    "site_vs_helper_jaccard": site_sims,
                    "site_vs_helper_containment": [round(containment(r, h_set), 3) for r in rem_sets],
                    "site_pairwise_jaccard": pairwise,
                    "removed": [len(s[2]) for s in sites],
                    "helper_lines": len(h.own_lines),
                },
            }
        )

    for case in cases:
        paths = [m["path"] for m in case["members"]] + ([case["helper"]["path"]] if "helper" in case else [])
        case["is_test"] = any(is_test(p) for p in paths)
    return cases


def cmd_mine(args: argparse.Namespace) -> None:
    data = json.loads((args.out / f"commits-{args.name}.json").read_text(encoding="utf-8"))
    git = Git(args.repo)
    stats: Counter = Counter()
    started = time.time()
    out_path = args.out / f"candidates-{args.name}.jsonl"
    commits = data["commits"][: args.limit] if args.limit else data["commits"]
    with out_path.open("w", encoding="utf-8") as out:
        for i, commit in enumerate(commits):
            stats["commits"] += 1
            if len(commit["parents"]) != 1:
                stats["skip_merge"] += 1
                continue
            if is_mega(commit):
                stats["skip_mega"] += 1
                continue
            if not is_candidate_commit(commit):
                stats["skip_no_modified_py"] += 1
                continue
            stats["mined"] += 1
            try:
                cases = mine_commit(git, commit, stats)
            except subprocess.CalledProcessError:
                stats["git_error"] += 1
                continue
            for case in cases:
                out.write(json.dumps({"repo": data["repo"], **case}) + "\n")
                stats[f"candidates_{case['kind']}{'_test' if case['is_test'] else ''}"] += 1
            if i % 200 == 0:
                print(f"{i}/{len(commits)} {time.time() - started:.0f}s {dict(stats)}", flush=True)
    stats["seconds"] = round(time.time() - started)
    (args.out / f"missing-{args.name}.txt").write_text("\n".join(sorted(git.missing)), encoding="utf-8")
    meta = {"repo": data["repo"], "head": data["head"], "stats": stats}
    meta["range"] = [commits[-1]["commit"], commits[0]["commit"], commits[-1]["date"], commits[0]["date"]]
    (args.out / f"mine-{args.name}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))


# ---------------------------------------------------------------- stage: select


def case_key(case: dict) -> str:
    parts = [case["kind"]] + sorted(
        f"{m['path']}::{m['qualname']}::{hashlib.sha1(m['code'].encode()).hexdigest()}" for m in case["members"]
    )
    if "helper" in case:
        parts.append(hashlib.sha1(case["helper"]["code"].encode()).hexdigest())
    return "|".join(parts)


def body_idents(code: str) -> set[str]:
    """Identifiers of a function's body, without its decorators, signature and docstring."""
    source = textwrap.dedent(code)
    try:
        node = ast.parse(source).body[0]
    except (SyntaxError, IndexError):
        return ident_set(code)
    body = getattr(node, "body", [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:]
    if not body:
        return set()
    return ident_set("\n".join(source.splitlines()[body[0].lineno - 1 :]))


def accept(case: dict, th: argparse.Namespace) -> str | None:
    """None when the case passes the thresholds, else the reason it is dropped."""
    f = case["features"]
    if case["kind"] == "pair-delete":
        case["members"][0]["removed_entirely"] = True
        a, b = (body_idents(m["code"]) for m in case["members"])
        f["a_in_b"] = round(len(a & b) / len(a), 3) if a else 0.0
        if f["a_calls_b"]:
            return "wrapper_inlined"
        if f["jaccard"] < th.delete_jaccard and f["a_in_b"] < th.delete_a_in_b:
            return "low_similarity"
    elif case["kind"] == "pair-shrink":
        if f["containment"] < th.shrink_containment or f["jaccard"] < th.shrink_jaccard:
            return "low_similarity"
    elif case["kind"] == "family":
        keep = [i for i, c in enumerate(f["site_vs_helper_containment"]) if c >= th.family_containment]
        if len(keep) < 2:
            return "low_similarity"
        if len(keep) < len(case["members"]):
            # drop the sites whose removed lines do not resemble the helper; the rest still form a family
            pairs = f["site_pairwise_jaccard"]
            f["site_pairwise_jaccard"] = [pairs[i * (i - 1) // 2 + j] for i in keep for j in keep if j < i]
            for name in ("site_vs_helper_jaccard", "site_vs_helper_containment", "removed"):
                f[name] = [f[name][i] for i in keep]
            f["sites_dropped"] = len(case["members"]) - len(keep)
            case["members"] = [case["members"][i] for i in keep]
            f["sites"] = len(keep)
    return None


def full_messages(out: Path, name: str) -> dict[str, str]:
    """Commit subject and body by sha, from the ``log`` stage files, for the keyword signal."""
    messages = {}
    for path in out.glob(f"commits-{name}*.json"):
        for c in json.loads(path.read_text(encoding="utf-8"))["commits"]:
            messages[c["commit"]] = c["subject"] + "\n" + c.get("body", "")
    return messages


def cmd_select(args: argparse.Namespace) -> None:
    summary = {"thresholds": {k: getattr(args, k) for k in THRESHOLDS}}
    for name in args.names:
        cand = [json.loads(line) for line in (args.out / f"candidates-{name}.jsonl").open(encoding="utf-8")]
        dropped: Counter = Counter()
        kept: dict[str, dict] = {}
        tests: Counter = Counter()
        messages = full_messages(args.out, name)
        for case in reversed(cand):  # oldest first: a cherry-picked repeat keeps its original commit
            if case["commit"] in messages:
                case["keyword_signal"] = bool(KEYWORDS.search(messages[case["commit"]]))
            reason = accept(case, args)
            if reason:
                dropped[f"{case['kind']}:{reason}"] += 1
                continue
            key = case_key(case)
            if key in kept:
                dropped[f"{case['kind']}:repeat"] += 1
                continue
            kept[key] = case
        cases = [c for c in kept.values() if not c["is_test"]]
        tests.update(c["kind"] for c in kept.values() if c["is_test"])
        with (args.out / f"cases-{name}.jsonl").open("w", encoding="utf-8") as fh:
            for case in reversed(cases):
                fh.write(json.dumps(case) + "\n")
        kinds = Counter(c["kind"] for c in cases)
        sizes = defaultdict(list)
        for c in cases:
            for m in c["members"]:
                sizes[c["kind"]].append(m["end_line"] - m["start_line"] + 1)
        summary[name] = {
            "candidates": len(cand),
            "cases": dict(kinds),
            "keyword_signal": dict(Counter(c["kind"] for c in cases if c["keyword_signal"])),
            "test_cases_skipped": dict(tests),
            "dropped": dict(dropped),
            "member_lines_quartiles": {k: quartiles(v) for k, v in sizes.items()},
            "family_sites": dict(Counter(c["features"]["sites"] for c in cases if c["kind"] == "family")),
        }
    text = json.dumps(summary, indent=1)
    (args.out / "summary.json").write_text(text, encoding="utf-8")
    print(text)


def quartiles(values: list[int]) -> dict:
    v = sorted(values)
    if not v:
        return {}
    pick = lambda q: v[min(len(v) - 1, int(q * len(v)))]  # noqa: E731
    return {"n": len(v), "min": v[0], "p25": pick(0.25), "median": pick(0.5), "p75": pick(0.75), "max": v[-1]}


# ---------------------------------------------------------------- stage: sample


def cmd_sample(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for name in args.names:
        for line in (args.out / f"cases-{name}.jsonl").open(encoding="utf-8"):
            case = json.loads(line)
            strata[(name, case["kind"])].append(case)
    keys = sorted(strata)
    per = max(1, args.n // max(1, len(keys)))
    picked: list[dict] = []
    for key in keys:
        pool = strata[key]
        picked += rng.sample(pool, min(per, len(pool)))
    rest = [c for k in keys for c in strata[k] if c not in picked]
    if len(picked) < args.n:
        picked += rng.sample(rest, min(args.n - len(picked), len(rest)))
    buf = io.StringIO()
    for i, case in enumerate(picked, 1):
        buf.write(f"\n{'=' * 100}\n#{i} {case['repo']} {case['kind']} {case['commit'][:10]} {case['date'][:10]}\n")
        buf.write(f"msg: {case['message']}\nkeyword: {case['keyword_signal']}  features: {case['features']}\n")
        for m in case["members"]:
            buf.write(f"--- member {m['path']}::{m['qualname']} @{m['rev'][:10]} L{m['start_line']}-{m['end_line']}\n")
            buf.write(clip(m["code"], args.max_lines) + "\n")
            if m.get("removed_lines"):
                buf.write("  [removed lines]\n" + clip("\n".join(m["removed_lines"]), args.max_lines) + "\n")
        if "helper" in case:
            h = case["helper"]
            buf.write(f"--- helper {h['path']}::{h['qualname']} @{h['rev'][:10]}\n{clip(h['code'], args.max_lines)}\n")
        if "callers" in case:
            buf.write(f"callers: {case['callers']}\n")
    sys.stdout.reconfigure(encoding="utf-8")
    print(buf.getvalue())


def clip(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[:n] + ([f"    ... ({len(lines) - n} more lines)"] if len(lines) > n else []))


# ---------------------------------------------------------------- cli

# Chosen by reading the candidates of the first 3,000 commits of each repository; see README.md.
THRESHOLDS = {
    "delete_jaccard": 0.3,
    "delete_a_in_b": 0.5,
    "shrink_containment": 0.5,
    "shrink_jaccard": 0.2,
    "family_containment": 0.4,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser, repo: bool = True) -> None:
        p.add_argument("--out", type=Path, required=True, help="directory for stage outputs")
        if repo:
            p.add_argument("--repo", type=Path, required=True, help="local clone (a blob:none partial clone works)")
            p.add_argument("--name", required=True, help="short repository name used in file names")

    p = sub.add_parser("log")
    common(p)
    p.add_argument("--commits", type=int, default=3000)
    p.add_argument("--rev", default="HEAD")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("fetch")
    common(p)
    p.add_argument("--batch", type=int, default=2000)
    p.add_argument("--floor-gb", type=float, default=4.0, help="stop when free disk falls below this")
    p.add_argument("--skip-tests", action="store_true", help="do not fetch test-file blobs")
    p.add_argument("--oids", type=Path, help="fetch the blob ids listed in this file instead")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("mine")
    common(p)
    p.add_argument("--limit", type=int, help="mine only the newest N listed commits (for trial runs)")
    p.set_defaults(func=cmd_mine)

    p = sub.add_parser("select")
    common(p, repo=False)
    p.add_argument("names", nargs="+")
    for k, v in THRESHOLDS.items():
        p.add_argument(f"--{k.replace('_', '-')}", type=float, default=v)
    p.set_defaults(func=cmd_select)

    p = sub.add_parser("sample")
    common(p, repo=False)
    p.add_argument("names", nargs="+")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--seed", type=int, default=20261111)
    p.add_argument("--max-lines", type=int, default=40)
    p.set_defaults(func=cmd_sample)

    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
