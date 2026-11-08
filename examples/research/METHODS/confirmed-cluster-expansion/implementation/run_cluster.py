# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, B023, B905, E401, E402, E741, I001
"""Offline cluster-conditioned retrieval. Writes only alongside this script; no judge calls."""

from _recovery_paths import recovery_path
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "2"
import sys

sys.dont_write_bytecode = True
if hasattr(os, "sched_getaffinity"):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
import pathlib, json, hashlib, collections, time, math, argparse, gzip

ROOT = pathlib.Path(recovery_path(""))
HERE = pathlib.Path(__file__).resolve().parent
BASE = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"
BANK = ROOT / "jobs/complementary-signal-learning/.lab-results/bank"
SRC = BASE / "runtime/src"
sys.path.insert(0, str(SRC))
import numpy as np
from dry_lint.models import Function, Candidate, evidence
from dry_lint.bench_background import BenchBackground
from dry_lint.detector import Detector
from dry_lint.comparers import TfidfComparer
from dry_lint.operation_blocks import OperationBlocksComparer, _GENERIC
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor
from dry_lint.settings import Settings
from dry_lint.judges.command import prompt, PROMPT_POLICIES

REF = "a10a288530c4aa25711c7ec3b86ac164d182899a"
USEFUL = {"duplicate", "drifted", "useful-extractable", "actionable-whole-duplication", "useful-bounded-extraction"}
NEGATIVE = {"separate", "already-shared", "related", "related/too-generic", "tiny-convenience", "tiny"}
METHODS = ["unseeded_changed_endpoint", "current_relatives_native", "reciprocal_anchored", "bounded_seed_diffusion"]


def sha(p):
    with pathlib.Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def canonical(x):
    return digest(json.dumps(x, sort_keys=True, ensure_ascii=True, allow_nan=False))


def jl(p):
    with gzip.open(p, "rt") if str(p).endswith(".gz") else pathlib.Path(p).open() as f:
        return [json.loads(l) for l in f if l.strip()]


def write(p, x):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    assert p.resolve().is_relative_to(HERE)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in x)
        if p.suffix == ".jsonl"
        else json.dumps(x, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    tmp.replace(p)


def safe(p):
    return not any(s in p["repository"].lower() for s in ["opencode", "firecrawl", "curator"])


def plan():
    if (HERE / "STAGED-PLAN.json").exists():
        return json.loads((HERE / "STAGED-PLAN.json").read_text())["cohorts"]
    steps = json.loads((BASE / "ordered-full-background-plan.json").read_text())["plan"]
    out = []
    small = 0
    for s in steps:
        if not safe(s):
            continue
        rp = BANK / s["cohort_id"] / "RECEIPT.json"
        r = json.loads(rp.read_text()) if rp.exists() else None
        smoke = bool(r and r["functions"] <= 2500 and small < 8)
        small += int(smoke)
        out.append(
            {
                "cohort_id": s["cohort_id"],
                "repository": s["repository"],
                "revision": s["revision"],
                "order": s["order"],
                "functions": s["documents"],
                "stage": 1 if smoke else 2,
                "bank_available": r is not None,
                "graph_mode": "all_source_nodes",
                "status": "planned",
                "missing_reason": None
                if smoke
                else "outside initial bounded smoke milestone; full all-node construction resource-unmeasured",
            }
        )
    write(
        HERE / "STAGED-PLAN.json",
        {
            "schema": 1,
            "selection": "Frozen original plan order; stage1 first8 available <=2500 nodes. Stage2 every remaining permitted cohort in same order, no label/rank selection. --stage extended --max-cohorts N resumes deterministic prefixes. Resource-bound missing coverage is explicit.",
            "holdout_excluded": ["anomalyco/opencode", "firecrawl", "curator"],
            "cohorts": out,
        },
    )
    return out


class Graph:
    def __init__(self, cid):
        self.cid = cid
        self.receipt = json.loads((BANK / cid / "RECEIPT.json").read_text())
        self.p = self.receipt["source"]
        p = self.p
        assert safe(p)
        for path, expected in [("functions_path", "functions_sha256"), ("background_path", "background_sha256")]:
            assert sha(p[path]) == p[expected]
        self.bg = BenchBackground.decode(pathlib.Path(p["background_path"]).read_bytes())
        self.idx = self.bg.index()
        self.fs = [
            Function.model_validate(r if r.get("line") is not None else r | {"line": 0, "end_line": -1})
            for r in jl(p["functions_path"])
        ]
        self.n = len(self.fs)
        counts = collections.Counter(f.qualname for f in self.fs)
        self.valid = [f.line > 0 and counts[f.qualname] == 1 for f in self.fs]
        for f, d in zip(self.fs, self.bg.documents, strict=True):
            assert f.qualname == d.id and digest(f.code) == d.source_sha256
            f.tokens = d.tokens()
        self.pos = {f.qualname: i for i, f in enumerate(self.fs)}
        self.lang = [
            f.analysis.language if f.analysis else ("python" if f.path.endswith(".py") else "typescript")
            for f in self.fs
        ]
        self.tie = sorted(range(self.n), key=lambda i: (self.fs[i].qualname, digest(self.fs[i].code), i))
        self.settings = Settings(
            neighbours=3, include=p["scope"]["include"], exclude=p["scope"]["exclude"], discovery={"enabled": False}
        )
        self.det = Detector(self.fs, self.settings, TfidfComparer(), [PythonExtractor(), TypeScriptExtractor()])
        self.ops = OperationBlocksComparer()
        self.ops.index(self.fs)
        self.api = [
            {
                t
                for t in f.tokens
                if t.startswith(("call:", "attr:", "key:")) and t.partition(":")[2].lower() not in _GENERIC
            }
            for f in self.fs
        ]
        self.df = collections.Counter(t for ts in self.api for t in ts)
        self.edges = {}
        self.adj = collections.defaultdict(dict)

    def eligible(self, q, t):
        return q != t and self.valid[q] and self.valid[t] and self.lang[q] == self.lang[t]

    def edge_id(self, q, t):
        return digest(f"{self.cid}:{q}:{t}")[:24]

    def regions(self, q, t):
        for fallback in (False, True):
            left = self.ops._query_blocks(self.fs[q], fallback=fallback)
            right = self.ops._query_blocks(self.fs[t], fallback=fallback)
            best = None
            for a in left:
                for b in right:
                    score, shared = self.ops._best([a], [b])
                    if score >= 0.65 and (best is None or score > best["score"]):
                        best = {
                            "score": score,
                            "query_span": [a.line, a.end_line],
                            "target_span": [b.line, b.end_line],
                            "shared_operations": shared,
                            "representation": "complete_helper_fallback" if fallback else "original_regions",
                        }
            if best:
                return [best]
        return []

    def build(self):
        dest = HERE / "graphs" / self.cid
        start = time.perf_counter()
        p = self.p
        key = canonical({"script": sha(__file__), "source": p, "graph_schema": 1})
        if (dest / "RECEIPT.json").exists():
            receipt = json.loads((dest / "RECEIPT.json").read_text())
            if receipt["cache_key"] == key:
                for e in jl(dest / "adjacency.jsonl"):
                    self.edges[e["edge_id"]] = e
                    self.adj[e["query_position"]][e["target_position"]] = e
                self.finish()
                return receipt
        vectors = None
        tail = None
        owners = None
        tailby = collections.defaultdict(list)
        if p.get("minilm_matrix_path"):
            assert sha(p["minilm_matrix_path"]) == p["minilm_matrix_sha256"]
            vectors = np.load(p["minilm_matrix_path"], mmap_mode="r")
            assert vectors.shape == (self.n, 384)
        if p.get("minilm_tail_matrix_path"):
            assert sha(p["minilm_tail_matrix_path"]) == p["minilm_tail_matrix_sha256"]
            views = jl(p["minilm_tail_views_path"])
            vby = {r["position"]: r for r in views}
            with np.load(p["minilm_tail_matrix_path"]) as z:
                tail = z["vectors"].copy()
                owners = z["owners"].astype(int)
                ords = z["ordinals"] if "ordinals" in z.files else [j for v in views for j in range(len(v["views"]))]
                for i, (o, k) in enumerate(zip(owners, ords, strict=True)):
                    v = vby[int(o)]["views"][int(k)]
                    assert digest(v["text"]) == v["input_sha256"]
                    tailby[int(o)].append(i)
        copies = collections.defaultdict(list)
        for i, f in enumerate(self.fs):
            copies[digest(f.code)].append(i)
        for q in range(self.n):
            if not self.valid[q]:
                continue
            tf = np.zeros(self.n)
            for t, s in self.idx.similar(self.fs[q].tokens):
                tf[t] = s
            scores = {"tfidf": tf}
            floors = {"tfidf": 0.35, "minilm_prefix": 0.65, "minilm_tail": 0.8}
            if vectors is not None:
                scores["minilm_prefix"] = vectors @ vectors[q]
            if tail is not None and vectors is not None:
                vals = np.full(self.n, -1.0, np.float32)
                qix = tailby[q]
                if qix:
                    vals = np.maximum(vals, (vectors @ tail[qix].T).max(axis=1))
                if len(tail):
                    query = np.vstack([vectors[q], tail[qix]]) if qix else vectors[q : q + 1]
                    np.maximum.at(vals, owners, (tail @ query.T).max(axis=1))
                scores["minilm_tail"] = vals
            found = collections.defaultdict(dict)
            for name, values in scores.items():
                order = sorted(
                    (t for t in self.tie if self.eligible(q, t) and values[t] >= floors[name]),
                    key=lambda t: -float(values[t]),
                )[:20]
                for rank, t in enumerate(order, 1):
                    found[t][name] = {"score": float(values[t]), "rank": rank}
            for rank, (f, s) in enumerate(
                self.ops.neighbours(self.fs[q], 64, lambda f: self.eligible(q, self.pos[f.qualname])), 1
            ):
                found[self.pos[f.qualname]]["operation_block"] = {"score": s, "rank": rank}
            for t in copies[digest(self.fs[q].code)]:
                if self.eligible(q, t):
                    found[t]["exact_source_copy"] = {"score": 1.0, "rank": 1}
            for t, signals in sorted(found.items()):
                common = sorted(self.api[q] & self.api[t])
                rare = [s for s in common if self.df[s] <= max(2, math.ceil(0.05 * self.n))]
                e = {
                    "schema": 1,
                    "edge_id": self.edge_id(q, t),
                    "cohort_id": self.cid,
                    "query_position": q,
                    "target_position": t,
                    "signals": signals,
                    "operation_evidence": self.regions(q, t) if "operation_block" in signals else [],
                    "shared_api_tokens": common,
                    "rare_shared_api_tokens": rare,
                    "same_file": self.fs[q].path == self.fs[t].path,
                    "weight": sum(
                        1 / (60 + min(v["rank"] for k, v in signals.items() if k in family))
                        for family in [
                            set(signals) & {"tfidf"},
                            set(signals) & {"minilm_prefix", "minilm_tail"},
                            set(signals) & {"operation_block"},
                            set(signals) & {"exact_source_copy"},
                        ]
                        if family
                    ),
                }
                self.edges[e["edge_id"]] = e
                self.adj[q][t] = e
        self.finish()
        write(
            dest / "adjacency.jsonl",
            sorted(self.edges.values(), key=lambda x: (x["query_position"], x["target_position"])),
        )
        nodes = []
        for i, f in enumerate(self.fs):
            nodes.append(
                {
                    "position": i,
                    "source_id": f.qualname,
                    "source_sha256": digest(f.code),
                    "path": f.path,
                    "line": f.line,
                    "end_line": f.end_line,
                    "source_characters": len(f.code),
                    "source_utf8_bytes": len(f.code.encode()),
                    "native_eligible": self.valid[i],
                    "indegree": self.indegree[i],
                    "hub": i in self.hubs,
                    "scc": int(self.scc[i]),
                    "weak_component": int(self.weak[i]),
                    "operation_regions": [
                        {"line": b.line, "end_line": b.end_line, "kind": b.kind, "tokens": sorted(b.operations)}
                        for b in self.ops._query_blocks(f, fallback=True)
                    ],
                }
            )
        write(dest / "nodes.jsonl", nodes)
        receipt = {
            "schema": 1,
            "cache_key": key,
            "product_commit": REF,
            "source": p,
            "bank_sha256": self.receipt["bank_sha256"],
            "nodes": self.n,
            "expanded_query_nodes": sum(self.valid),
            "bank_queries": self.receipt["queries"],
            "edges": len(self.edges),
            "hubs": len(self.hubs),
            "scc_scope": "global over retained full-source top20-per-signal graph, not full similarity relation",
            "max_scc": max(collections.Counter(self.scc).values()),
            "max_weak_component": max(collections.Counter(self.weak).values()),
            "seconds": time.perf_counter() - start,
            "adjacency_sha256": sha(dest / "adjacency.jsonl"),
            "label_inputs": [],
            "threads": 2,
        }
        write(dest / "RECEIPT.json", receipt)
        return receipt

    def finish(self):
        self.indegree = collections.Counter(t for q in self.adj for t in self.adj[q])
        self.hubs = {t for t, c in self.indegree.items() if c > max(20, math.ceil(0.02 * self.n))}
        ii = [e["query_position"] for e in self.edges.values()]
        jj = [e["target_position"] for e in self.edges.values()]
        reverse = collections.defaultdict(list)
        for x, y in zip(ii, jj):
            reverse[y].append(x)
        seen = set()
        order = []
        for root in range(self.n):
            if root in seen:
                continue
            seen.add(root)
            stack = [(root, iter(self.adj[root]))]
            while stack:
                node, it = stack[-1]
                child = next(it, None)
                if child is None:
                    order.append(node)
                    stack.pop()
                elif child not in seen:
                    seen.add(child)
                    stack.append((child, iter(self.adj[child])))
        self.scc = [-1] * self.n
        component = 0
        for root in reversed(order):
            if self.scc[root] >= 0:
                continue
            stack = [root]
            self.scc[root] = component
            while stack:
                node = stack.pop()
                for child in reverse[node]:
                    if self.scc[child] < 0:
                        self.scc[child] = component
                        stack.append(child)
            component += 1
        self.weak = [-1] * self.n
        component = 0
        for root in range(self.n):
            if self.weak[root] >= 0:
                continue
            stack = [root]
            self.weak[root] = component
            while stack:
                node = stack.pop()
                for child in set(self.adj[node]) | set(reverse[node]):
                    if self.weak[child] < 0:
                        self.weak[child] = component
                        stack.append(child)
            component += 1

    def anchor(self, a, t):
        return sorted(s for s in self.api[a] & self.api[t] if self.df[s] <= max(2, math.ceil(0.05 * self.n)))

    def proposals(self, a, b, method):
        if method == "unseeded_changed_endpoint":
            return [
                (a, t, [a, t], e["weight"], {"route": "unseeded_changed_endpoint"})
                for t, e in self.adj[a].items()
                if t != b
            ]
        if method == "current_relatives_native":
            raise ValueError("Use real detector")
        paths = {}
        seeds = {a, b}
        for anchor in (a, b):
            for t in self.adj[anchor]:
                if t not in seeds:
                    paths[(anchor, t)] = [anchor, t]
            for u in self.adj[anchor]:
                if u in self.hubs and u not in seeds:
                    continue
                for t in self.adj[u]:
                    if t not in seeds and (anchor, t) not in paths:
                        paths[(anchor, t)] = [anchor, u, t]
        reachable = seeds | {t for _, t in paths}
        mass = {a: 0.5, b: 0.5}
        for _ in range(4):
            new = {a: 0.25, b: 0.25}
            for u, m in sorted(mass.items()):
                if u in self.hubs and u not in seeds:
                    continue
                valid = [
                    (t, e["weight"] / math.sqrt(1 + self.indegree[t])) for t, e in self.adj[u].items() if t in reachable
                ]
                denom = sum(w for _, w in valid)
                if denom:
                    for t, w in valid:
                        new[t] = new.get(t, 0) + 0.5 * m * w / denom
            mass = new
        out = []
        for (anchor, t), path in sorted(paths.items()):
            rare = self.anchor(anchor, t)
            exact = self.fs[anchor].code == self.fs[t].code
            if len(rare) < 2 and not exact:
                continue
            reciprocal = all(x in self.adj[y] for x, y in zip(path, path[1:]))
            shared = set(self.adj[anchor]) & set(self.adj[t])
            supported = [u for u in shared if u not in self.hubs and len(set(rare) & self.api[u]) >= 2]
            both = t in self.adj[a] and t in self.adj[b]
            if method == "reciprocal_anchored" and not (
                exact or len(path) == 2 and (reciprocal or both) or len(path) == 3 and reciprocal and supported
            ):
                continue
            score = (
                mass.get(t, 0)
                if method == "bounded_seed_diffusion"
                else sum(self.adj[x][y]["weight"] for x, y in zip(path, path[1:])) / (len(path) - 1)
            )
            out.append(
                (
                    anchor,
                    t,
                    path,
                    score,
                    {
                        "rare_anchor_tokens": rare,
                        "reciprocal_path": reciprocal,
                        "shared_neighbor_support": sorted(supported),
                        "both_endpoints_direct": both,
                        "target_hub": t in self.hubs,
                        "same_retained_scc": bool(self.scc[anchor] == self.scc[t]),
                        "exact_source_copy": exact,
                    },
                )
            )
        return out


def load_recorded_seeds(g):
    """Exact recorded prompt + candidate + source, no client construction or execution."""
    found = []
    audit = collections.Counter()
    packet_cache = {}
    for folder in ("encoder-judging", "combined-judging", "enablement-judging"):
        for path in sorted((ROOT / ".lab-results" / folder / "physical-account/observations").glob("*.json")):
            row = json.loads(path.read_text())
            ident = row.get("identity", {})
            if (
                ident.get("background_sha256") != g.p["background_sha256"]
                or ident.get("repository") != g.p["repository"]
                or ident.get("revision") != g.p["revision"]
            ):
                continue
            audit["same_source_observations"] += 1
            if ident.get("kind") != "claude" or ident.get("scope") != g.p["scope"]:
                audit["unsupported_prompt_or_scope"] += 1
                continue
            if (
                ident.get("model") != "claude-haiku-5-5"
                or ident.get("max_output_tokens") != 2048
                or ident.get("version") != PROMPT_POLICIES["shared-operations"][0] + ":claude-haiku-5-5:output=2048"
            ):
                audit["unsupported_prompt_or_scope"] += 1
                continue
            pf = pathlib.Path(row["packet_file"])
            if not pf.exists() or sha(pf) != row["packet_file_sha256"]:
                audit["missing_packet"] += 1
                continue
            if str(pf) not in packet_cache:
                packet_cache[str(pf)] = jl(pf)
            candidates = [
                r["candidate"]
                for r in packet_cache[str(pf)]
                if r.get("candidate") and canonical(r["candidate"]) == ident.get("candidate_sha256")
            ]
            if len(candidates) != 1:
                audit["candidate_hash_unmatched"] += 1
                continue
            c = Candidate.model_validate(candidates[0])
            if (
                prompt(c, policy="shared-operations") != ident["rendered_input"]
                or c.context_hash != ident["context_hash"]
                or evidence(c) != ident["source_evidence"]
                or canonical(ident) != row["request_key"]
            ):
                audit["exact_prompt_mismatch"] += 1
                continue
            positions = []
            for f in (c.new, c.existing):
                pos = g.pos.get(f.qualname)
                if (
                    pos is None
                    or g.fs[pos].code != f.code
                    or (g.fs[pos].line, g.fs[pos].end_line) != (f.line, f.end_line)
                ):
                    break
                positions.append(pos)
            if len(positions) != 2:
                audit["source_body_mismatch"] += 1
                continue
            v = row.get("verdict")
            settings = ident.get("settings", {})
            if (
                row.get("error")
                or not v
                or v["label"] not in {"duplicate", "drifted"}
                or v["score"] < settings.get("report_at", 1)
            ):
                audit["nonreported_or_unanswered"] += 1
                continue
            audit["exact_provider_confirmations"] += 1
            found.append(
                {
                    "seed_mode": "real_prior_judge_confirmed",
                    "provider_confirmed": True,
                    "independently_source_confirmed": False,
                    "historical_report_emission_verified": False,
                    "reporting_basis": "recorded verdict satisfies recorded report_at; retrospective exposure, not proof of actual deployment report",
                    "candidate": c.model_dump(mode="json"),
                    "positions": positions,
                    "lane": c.lane,
                    "observation_path": str(path),
                    "observation_sha256": sha(path),
                    "request_key": row["request_key"],
                    "prompt_sha256": digest(ident["rendered_input"]),
                    "judge_contract": {
                        k: ident.get(k)
                        for k in ["model", "version", "max_output_tokens", "request_options", "settings"]
                    },
                    "verdict": v,
                }
            )
    # Same exact source pair is one exposure, despite several recorded requests.
    unique = {}
    for s in found:
        unique.setdefault(tuple(sorted(s["positions"])), s)
    return list(unique.values()), dict(audit)


def targets(g):
    rows = jl(BANK / g.cid / "targets.jsonl")
    inventory = {}
    with (ROOT / "jobs/cross-repo-recall-audit/.lab-results/inventory-rows.jsonl").open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("repository") != g.p["repository"]:
                continue
            inventory[r["row_id"]] = r
    out = []
    for row in rows:
        i = inventory.get(row["row_id"], {})
        if i.get("wave_role") == "holdout":
            raise AssertionError("reserved outcome")
        out.append(
            row
            | {
                "source_component": i.get("component", row["family_component"]),
                "label_scope": i.get("label_scope", "unknown"),
                "whole_function_label": i.get("whole_function_label"),
                "current_label": i.get("current_label", row["label"]),
                "authority": i.get("authority", "existing registry"),
                "source_review_status": i.get("source_review_status", "unknown"),
            }
        )
    return out


def run(args):
    started = time.perf_counter()
    stages = plan()
    selected = [p for p in stages if p["bank_available"] and (args.stage == "extended" or p["stage"] == 1)]
    if args.max_cohorts:
        selected = selected[: args.max_cohorts]
    proposals = []
    exposures = []
    outcomes = []
    metrics = []
    receipts = []
    audits = []
    seen_families = set()
    frontier = {}
    seed_counter = collections.Counter()
    for ps in selected:
        cid = ps["cohort_id"]
        print("building", cid, ps["functions"], flush=True)
        g = Graph(cid)
        receipt = g.build()
        receipts.append(receipt)
        # Outcomes are first opened only after this cohort's complete label-free graph is materialized.
        ts = targets(g)
        by_pair = collections.defaultdict(list)
        for r in ts:
            by_pair[tuple(sorted(r["query_positions"]))].append(r)
        real, audit = load_recorded_seeds(g)
        audits.append({"cohort_id": cid, **audit})
        seeds = list(real)
        for s in seeds:
            match = by_pair.get(tuple(sorted(s["positions"])), [])
            s["source_assessment"] = [
                {"row_id": r["row_id"], "label": r["current_label"], "authority": r["authority"]} for r in match
            ]
            s["independently_source_confirmed"] = any(
                r["accepted_gold"] and r["current_label"] in USEFUL for r in match
            )
            s["source_component"] = next(
                (r["source_component"] for r in match), "unmapped-recorded:" + digest(str(sorted(s["positions"])))
            )
        for r in sorted(ts, key=lambda r: r["row_id"]):
            if not r["canonical_evaluation"]:
                continue
            label = r["current_label"]
            component = r["source_component"]
            if label in USEFUL and r["accepted_gold"] and component not in seen_families:
                seen_families.add(component)
                # Oracle baseline/exploration are paired eligibility controls, not independent confirmations.
                for lane in ("baseline", "exploration"):
                    seeds.append(
                        {
                            "seed_mode": "source_gold_oracle_replay",
                            "positions": r["query_positions"],
                            "lane": lane,
                            "source_component": component,
                            "row_id": r["row_id"],
                            "provider_confirmed": False,
                            "independently_source_confirmed": True,
                            "label_scope": r["label_scope"],
                        }
                    )
            elif label in NEGATIVE:
                seeds.append(
                    {
                        "seed_mode": "false_seed_control",
                        "positions": r["query_positions"],
                        "lane": "baseline",
                        "source_component": component,
                        "row_id": r["row_id"],
                        "control_label": label,
                        "provider_confirmed": False,
                        "independently_source_confirmed": False,
                    }
                )
        # Registry rows can repeat the same pair. One exposure per exact mode/lane/pair,
        # preserving all row provenance without multiplying the review denominator.
        unique_seeds = {}
        for seed in seeds:
            key = (seed["seed_mode"], seed["lane"], tuple(seed["positions"]))
            if key not in unique_seeds:
                unique_seeds[key] = seed | {"supporting_row_ids": [seed["row_id"]] if "row_id" in seed else []}
            elif "row_id" in seed:
                unique_seeds[key]["supporting_row_ids"].append(seed["row_id"])
        seeds = list(unique_seeds.values())
        bankqueries = {r["query_position"] for r in jl(BANK / cid / "queries.jsonl")}
        for si, seed in enumerate(seeds):
            a, b = seed["positions"]
            if not g.eligible(a, b):
                continue
            parent = (
                Candidate.model_validate(seed["candidate"])
                if "candidate" in seed
                else g.det.pair(g.fs[a], g.fs[b], g.det.comparer.similarity(g.fs[a], g.fs[b])).model_copy(
                    update={"lane": seed["lane"]}
                )
            )
            # Native candidate JSON intentionally excludes extractor tokens. Recorded
            # seeds need exact index tokens restored before native relatives runs.
            parent = parent.model_copy(
                update={
                    "new": parent.new.model_copy(update={"tokens": g.fs[a].tokens}),
                    "existing": parent.existing.model_copy(update={"tokens": g.fs[b].tokens}),
                }
            )
            seedid = digest(f"{cid}:{seed['seed_mode']}:{seed['lane']}:{a}:{b}")[:24]
            exposure = {k: v for k, v in seed.items() if k != "candidate"} | {
                "schema": 1,
                "seed_id": seedid,
                "cohort_id": cid,
                "seed_pair_key": parent.key,
                "repository": g.p["repository"],
                "revision": g.p["revision"],
                "source": g.p,
                "seed_candidate": parent.model_dump(mode="json"),
            }
            exposures.append(exposure)
            seed_counter[seed["seed_mode"]] += 1
            native = g.det.relatives([g.fs[a]], [parent])
            native_by = {(g.pos[c.new.qualname], g.pos[c.existing.qualname]): c for c in native}
            native_pairs = {tuple(sorted(k)) for k in native_by}
            unseeded_native = {tuple(sorted((a, g.pos[f.qualname]))) for f, _ in g.det.neighbours(g.fs[a])}
            seedpair = tuple(sorted((a, b)))
            seed_component = seed.get("source_component")
            sibling_gold = {
                pair
                for pair, rs in by_pair.items()
                if pair != seedpair
                and any(r["current_label"] in USEFUL and r["source_component"] == seed_component for r in rs)
            }
            for method in METHODS:
                tick = time.perf_counter()
                if method == "current_relatives_native":
                    items = [
                        (q, t, [q, t], c.similarity, {"route": "native Detector.relatives"})
                        for (q, t), c in native_by.items()
                    ]
                else:
                    items = g.proposals(a, b, method)
                if method in METHODS[2:]:
                    items = [(q, t, [q, t], 1.0, {"route": "protected_native_relative"}) for q, t in native_by] + items
                items = sorted(
                    items,
                    key=lambda x: (
                        x[4].get("route") != "protected_native_relative",
                        -x[3],
                        g.fs[x[0]].qualname,
                        g.fs[x[1]].qualname,
                    ),
                )
                seen = set()
                used = {a, b}
                chars = 0
                records = []
                rejected = collections.Counter()
                for q, t, path, score, why in items:
                    pair = tuple(sorted((q, t)))
                    if pair == seedpair or pair in seen:
                        continue
                    seen.add(pair)
                    c = native_by.get((q, t)) or g.det.pair(
                        g.fs[q], g.fs[t], g.det.comparer.similarity(g.fs[q], g.fs[t])
                    ).model_copy(
                        update={
                            "comparer": "cluster-graph:1",
                            "lane": "relative",
                            "parent": parent.key,
                            "similarity_reusable": False,
                        }
                    )
                    if c.filtered:
                        rejected["native_rule:" + c.filtered] += 1
                        continue
                    newchars = sum(len(g.fs[i].code) for i in {q, t} - used)
                    if chars + newchars > 60000 and pair not in native_pairs:
                        rejected["source_character_budget"] += 1
                        continue
                    used |= {q, t}
                    chars += newchars
                    labels = by_pair.get(pair, [])
                    record = {
                        "schema": 1,
                        "proposal_id": digest(f"{seedid}:{method}:{q}:{t}")[:24],
                        "seed_id": seedid,
                        "seed_pair_key": parent.key,
                        "seed_mode": seed["seed_mode"],
                        "seed_lane": seed["lane"],
                        "cohort_id": cid,
                        "method": method,
                        "query_position": q,
                        "target_position": t,
                        "repository": g.p["repository"],
                        "revision": g.p["revision"],
                        "scope": g.p["scope"],
                        "functions_sha256": g.p["functions_sha256"],
                        "background_sha256": g.p["background_sha256"],
                        "source_artifact": g.p["functions_path"],
                        "candidate": c.model_dump(mode="json"),
                        "source_body_sha256": [digest(g.fs[q].code), digest(g.fs[t].code)],
                        "path": [g.fs[i].qualname for i in path],
                        "path_positions": path,
                        "edge_ids": [g.edge_id(x, y) for x, y in zip(path, path[1:]) if y in g.adj[x]],
                        "depth": len(path) - 1,
                        "operation_identity": {
                            "scope": "retrieval region only; no equivalence assertion",
                            "regions": g.regions(q, t),
                            "anchor_api_tokens": g.anchor(q, t),
                        },
                        "evidence": why,
                        "ranking_score": score,
                        "confidence": None,
                        "status": "supported_unjudged",
                        "reported": False,
                        "blocking": False,
                        "related": False,
                        "incremental_vs_current_relatives": pair not in native_pairs,
                        "incremental_vs_unseeded_native": pair not in unseeded_native,
                        "target_was_bank_query": t in bankqueries,
                        "source_characters_incremental": newchars,
                        "source_characters_total": sum(len(g.fs[i].code) for i in {q, t}),
                        "source_tokens_proxy": math.ceil(sum(len(g.fs[i].code.encode()) for i in {q, t}) / 4),
                        "source_component": seed_component,
                    }
                    proposals.append(record)
                    records.append(record)
                    outcomes.append(
                        {
                            "proposal_id": record["proposal_id"],
                            "seed_id": seedid,
                            "method": method,
                            "pair": list(pair),
                            "labels": [
                                {
                                    "row_id": r["row_id"],
                                    "label": r["current_label"],
                                    "accepted_gold": r["accepted_gold"],
                                    "source_component": r["source_component"],
                                    "label_scope": r["label_scope"],
                                    "whole_function_label": r["whole_function_label"],
                                    "authority": r["authority"],
                                }
                                for r in labels
                            ]
                            or [{"label": "unknown"}],
                        }
                    )
                    if (
                        not labels
                        and pair not in native_pairs
                        and method in METHODS[2:]
                        and seed["seed_mode"] != "false_seed_control"
                    ):
                        frontier.setdefault((cid, pair), record)
                got = {tuple(sorted((r["query_position"], r["target_position"]))) for r in records}
                known = [by_pair[p] for p in got if p in by_pair]
                useful = {p for p in got if any(r["current_label"] in USEFUL for r in by_pair.get(p, []))}
                negative = {p for p in got if any(r["current_label"] in NEGATIVE for r in by_pair.get(p, []))}
                metrics.append(
                    {
                        "seed_id": seedid,
                        "cohort_id": cid,
                        "method": method,
                        "seed_mode": seed["seed_mode"],
                        "seed_lane": seed["lane"],
                        "source_component": seed_component,
                        "proposals": len(records),
                        "additional_proposals": len(got - native_pairs),
                        "known_useful": len(useful),
                        "incremental_known_useful": len(useful - native_pairs),
                        "known_negative_exposure": len(negative),
                        "unknown": sum(p not in by_pair for p in got),
                        "known_other": len(known) - len(useful | negative),
                        "known_precision_numerator": len(useful),
                        "known_precision_denominator": len(useful | negative),
                        "conditional_sibling_recall_numerator": len(got & sibling_gold),
                        "conditional_sibling_recall_denominator": len(sibling_gold),
                        "unique_useful_families": sorted(
                            {r["source_component"] for p in useful for r in by_pair[p] if r["current_label"] in USEFUL}
                        ),
                        "incremental_useful_families": sorted(
                            {
                                r["source_component"]
                                for p in useful - native_pairs
                                for r in by_pair[p]
                                if r["current_label"] in USEFUL
                            }
                        ),
                        "lost_native_proposals": len(native_pairs - got) if method in METHODS[2:] else None,
                        "marginal_source_characters": chars,
                        "unique_source_tokens_proxy": math.ceil(
                            sum(len(g.fs[i].code.encode()) for i in used - {a, b}) / 4
                        ),
                        "seconds": time.perf_counter() - tick,
                        "rejected": dict(rejected),
                    }
                )
        ps["status"] = "executed"
        ps["missing_reason"] = None
        # Publish reusable artifacts incrementally for sibling consumers.
        for name, data in [
            ("seed-exposures", exposures),
            ("proposals", proposals),
            ("outcomes", outcomes),
            ("metrics", metrics),
            ("recorded-seed-audit", audits),
            ("frontier-handoff", list(frontier.values())),
        ]:
            write(HERE / (name + ".jsonl"), data)
        write(
            HERE / "STATUS.json",
            {
                "stage": "running smoke replay" if args.stage == "smoke" else "running extended replay",
                "completed_cohorts": len(receipts),
                "provider_calls": 0,
                "seeds": dict(seed_counter),
                "proposals": len(proposals),
                "unknown_frontier_pairs": len(frontier),
            },
        )
        print("complete", cid, "edges", receipt["edges"], "seeds", len(seeds), "proposals", len(proposals), flush=True)
    groups = collections.defaultdict(list)
    for m in metrics:
        groups[(m["seed_mode"], m["seed_lane"], m["method"])].append(m)
    summary = []
    for (mode, lane, method), ms in sorted(groups.items()):
        counts = {
            k: sum(m[k] for m in ms)
            for k in [
                "proposals",
                "additional_proposals",
                "known_useful",
                "incremental_known_useful",
                "known_negative_exposure",
                "unknown",
                "known_other",
                "known_precision_numerator",
                "known_precision_denominator",
                "conditional_sibling_recall_numerator",
                "conditional_sibling_recall_denominator",
                "marginal_source_characters",
                "unique_source_tokens_proxy",
            ]
        }
        summary.append(
            {
                "seed_mode": mode,
                "seed_lane": lane,
                "method": method,
                "seed_exposures": len(ms),
                "unique_seed_components": len({m["source_component"] for m in ms}),
                "unique_reached_useful_components": len({f for m in ms for f in m["unique_useful_families"]}),
                "unique_incremental_useful_components": len({f for m in ms for f in m["incremental_useful_families"]}),
                "max_sibling_count": max(m["proposals"] for m in ms),
                "median_sibling_count": float(np.median([m["proposals"] for m in ms])),
                **counts,
            }
        )
    write(
        HERE / "RESULTS.json",
        {
            "schema": 1,
            "stage": args.stage,
            "interpretation": "Functional smoke screen; no population precision, deployment recall, or acceptance claim. Scores rank explicitly speculative nonblocking leads. Labeled subset precision is selected and incomplete. Repeated exposures are not independent families.",
            "graphs": receipts,
            "summary": summary,
            "coverage": stages,
            "seconds": time.perf_counter() - started,
            "provider_calls": 0,
            "physical_usd": 0,
            "recorded_seed_audit": audits,
            "unknown_frontier_pairs": len(frontier),
            "real_scheduler_owner": "adaptive-judge-budget",
            "script_sha256": sha(__file__),
        },
    )
    write(
        HERE / "STATUS.json",
        {
            "stage": "executed useful milestone",
            "cohorts": len(receipts),
            "pending_available_development_cohorts": sum(s["bank_available"] for s in stages) - len(receipts),
            "planned_without_bank_receipt": sum(not s["bank_available"] for s in stages),
            "provider_calls": 0,
            "seeds": dict(seed_counter),
            "proposals": len(proposals),
            "unknown_frontier_pairs": len(frontier),
            "limitations": [
                "smoke screen only",
                "oracle versus provider confirmations separated",
                "unverified siblings are nonblocking leads",
                "monetary budget and actual review latency not measured",
                "opencode outcomes unopened",
            ],
            "next": "root funding and sibling calibration; deterministic remaining-cohort staged extension",
        },
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["smoke", "extended"], default="smoke")
    ap.add_argument("--max-cohorts", type=int)
    run(ap.parse_args())
