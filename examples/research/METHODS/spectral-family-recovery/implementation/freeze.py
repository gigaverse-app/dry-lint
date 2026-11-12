# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F401, I001, UP017
from _recovery_paths import recovery_path
import json, pathlib, hashlib, datetime

H = pathlib.Path(__file__).resolve().parent
G = pathlib.Path(recovery_path("jobs/confirmed-cluster-expansion/.lab-results"))
contract = {
    "schema": 1,
    "worker": "spectral-family-recovery",
    "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "product_commit": "a10a288530c4aa25711c7ec3b86ac164d182899a",
    "product_src": recovery_path("jobs/encoder-corpus-evaluation/.lab-results/runtime/src"),
    "threads": 2,
    "providers": 0,
    "graph": {
        "input": "reuse exact all-node graphs from confirmed-cluster-expansion, read-only",
        "floor": {
            "tfidf": 0.35,
            "minilm_prefix": 0.65,
            "minilm_tail": 0.8,
            "operation_block": "native guarded comparer",
        },
        "per_signal_top_neighbors": 20,
        "operation_parent_bound": 64,
        "weights": "sum reciprocal rank 1/(60+rank) per independent signal family; prefix/tail count once",
        "self_edges": False,
        "primary_symmetrization": "mutual minimum directional weight",
        "diagnostic_symmetrization": "union maximum directional weight",
        "isolates": "retain, never force links",
    },
    "spectral": {
        "operator": "symmetric normalized Laplacian I-D^-1/2 W D^-1/2; sweep v2/sqrt(degree)",
        "partition": "connected components separately; min 3 nodes each side, minimum conductance sweep",
        "accept_cut_max_conductance": 0.20,
        "stability": "deterministic +/-5% undirected edge-weight perturbation; orientation-invariant partition agreement >=.90",
        "max_depth": 4,
        "min_partition_nodes": 6,
        "solver": "sparse eigsh, k=2, deterministic initial vector, tolerance 1e-6, maxiter=3000; failures abstain",
        "seed_region": "union of leaf regions containing either seed endpoint, native relatives protected",
        "overlap": "graph-derived seed-region ordering plus all eligible bounded-diffusion leads retained; shared seed operation signature must occur within one bounded region of BOTH seed endpoints and each member; >=2 nongeneric rare API tokens, >=1 call/attr; separate overlapping groups per signature, no transitive pairwise-fragment union",
        "ranking": "protected native first; supported common operation group first; seed leaf membership next; original diffusion score last; unsupported alternatives retained",
    },
    "diagnostics": [
        "mutual versus union",
        "threshold floors +.05, no retuning",
        "edge perturbation",
        "hubs/boilerplate",
        "after-refactor and false seeds",
        "cheap shared-operation-only ranking ablation",
    ],
    "evaluation": {
        "scenarios": "exact published graph-worker one-seed exposures; oracle positive, exact recorded provider positive, false seed separate",
        "outcomes": "only join after graphs/queues; no other gold positives in features",
        "budgets": "same max 60000 extra source characters; top3/10/20 and full frontier review exposure with unique source+context token proxy",
        "same_operation": "source-grounded toy operation truth; real common token/region evidence is hypothesis not operation truth",
        "funding": "real $0.04 reporting NOT run; root-owned exact pre-execution SQLite backup/normal ledger and one pin/repo required",
        "unknown": "never negative",
    },
    "scope": "first8 already-selected graphs smoke only; deterministic continuation all56 available development backgrounds in original order, remaining21 no-bank entries separate; no opencode/firecrawl/curator opened",
    "svd": "not run: adjacency eigenvectors distinct from TFIDF SVD; reuse prior vector-expansion negative studies",
    "decision_rule": "iterate only if fewer known-negative/unknown leads at comparable known useful coverage; no ship without independent operation review and funded matched reporting",
    "references": [
        "https://www.cs.cmu.edu/~jshi/papers/pami_ncut.pdf",
        "https://snap.stanford.edu/class/cs224w-readings/andersen06localgraph.pdf",
        "https://jmlr2020.csail.mit.edu/papers/v13/mahoney12a.html",
    ],
}
for name, data in [
    ("SPECTRAL-CONTRACT.json", contract),
    (
        "STATUS.json",
        {
            "schema": 1,
            "stage": "frozen before spectral outcomes",
            "provider_calls": 0,
            "writes": ".lab-results only",
            "next": "toy controls then exact eight graph smoke; deterministic broad continuation plan",
        },
    ),
    ("CONTINUATION.json", json.loads((G / "STAGED-PLAN.json").read_text())),
]:
    (H / name).write_text(json.dumps(data, indent=2) + "\n")
