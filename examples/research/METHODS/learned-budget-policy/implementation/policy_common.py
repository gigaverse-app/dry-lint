# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E741, I001
from _recovery_paths import recovery_path
import os, sys, pathlib, json, hashlib

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[k] = "2"
sys.dont_write_bytecode = True
H = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
B = ROOT / "jobs/complementary-signal-learning/.lab-results"
D = B / "deterministic-v2"
A = ROOT / "jobs/cross-repo-recall-audit/.lab-results"
R = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"
REF = "a10a288530c4aa25711c7ec3b86ac164d182899a"


def jl(p):
    with pathlib.Path(p).open() as f:
        return [json.loads(l) for l in f if l.strip()]


def write(p, obj):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    s = (
        "".join(json.dumps(x, sort_keys=True, allow_nan=False) + "\n" for x in obj)
        if p.suffix == ".jsonl"
        else json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(s)
    tmp.replace(p)


def sha(p):
    with pathlib.Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(x):
    return hashlib.sha256(x.encode()).hexdigest()


def group(repo):
    return (
        "due-backend-lineage"
        if repo in ["gigaverse-app/due", "gigaverse-app/backend-common", "gigaverse-app/gigaverse-backend"]
        else repo
    )


SCORES = ["tfidf", "minilm", "tail", "block", "containment"]
FEATURES = (
    [x + "_score" for x in SCORES]
    + [x + "_log_rank" for x in SCORES]
    + [x + "_cross_log_rank" for x in SCORES]
    + [x + "_background_z" for x in SCORES]
    + [
        "prefix_tail_min",
        "prefix_tail_gap",
        "sparse_dense_product",
        "shared_api_log",
        "shared_idf_log",
        "contract_jaccard",
        "length_ratio",
        "query_lines_log",
        "target_lines_log",
        "same_file",
        "same_name",
        "minilm_available",
        "tail_available",
        "block_supported",
        "contract_available",
        "forwarding",
        "direct_call",
        "same_owner",
        "structural_equal",
        "calls_jaccard",
        "calls_containment",
        "normal_cost_log",
        "review_minutes_log",
    ]
)
