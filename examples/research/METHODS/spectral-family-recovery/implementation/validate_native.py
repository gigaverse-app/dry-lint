# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, E741, I001
"""Pin imports and replay native relatives with the product Python, never a judge."""

from _recovery_paths import recovery_path
import os, sys

sys.dont_write_bytecode = True
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[k] = "2"
if hasattr(os, "sched_getaffinity"):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
import pathlib, json, hashlib, subprocess, shutil, collections

H = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
G = ROOT / "jobs/confirmed-cluster-expansion/.lab-results"
SRC = ROOT / "jobs/encoder-corpus-evaluation/.lab-results/runtime/src"
PIN = "a10a288530c4aa25711c7ec3b86ac164d182899a"
sys.path.insert(0, str(SRC))
sys.path.insert(1, str(G))
import dry_lint, run_cluster as g

assert pathlib.Path(dry_lint.__file__).is_relative_to(SRC)


def sha(p):
    with pathlib.Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write(name, data):
    (H / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


files = subprocess.check_output(
    ["git", "ls-tree", "-r", "--name-only", PIN, "src/dry_lint"], cwd=ROOT / "jobs/encoder-corpus-evaluation", text=True
).splitlines()
checked = []
for f in files:
    if not f.endswith(".py"):
        continue
    p = SRC / pathlib.Path(f).relative_to("src")
    assert p.read_bytes() == subprocess.check_output(
        ["git", "show", PIN + ":" + f], cwd=ROOT / "jobs/encoder-corpus-evaluation"
    ), f
    checked.append({"file": f, "sha256": sha(p)})
# Snapshot producer files once. Subsequent broad worker runs cannot replace smoke inputs.
I = H / "inputs"
I.mkdir(exist_ok=True)
if not (I / "SNAPSHOT.json").exists():
    manifest = []
    selected = [r["cohort_id"] for r in json.loads((H / "SOURCE-MATRIX.json").read_text())]
    for name in [
        "seed-exposures.jsonl",
        "proposals.jsonl",
        "outcomes.jsonl",
        "metrics.jsonl",
        "CONTROL-INVENTORY.jsonl",
    ]:
        shutil.copyfile(G / name, I / name)
        manifest.append({"path": name, "sha256": sha(I / name)})
    for cid in selected:
        for name in ["nodes.jsonl", "adjacency.jsonl", "RECEIPT.json"]:
            dest = I / "graphs" / cid / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(G / "graphs" / cid / name, dest)
            manifest.append({"path": str(dest.relative_to(I)), "sha256": sha(dest)})
    (I / "SNAPSHOT.json").write_text(json.dumps(manifest, indent=2) + "\n")
for r in json.loads((I / "SNAPSHOT.json").read_text()):
    assert sha(I / r["path"]) == r["sha256"]
seeds = {r["seed_id"]: r for r in g.jl(I / "seed-exposures.jsonl")}
props = g.jl(H / "ranked-leads.jsonl")
queues = g.jl(H / "queues.jsonl")
count = collections.Counter()
for folder in sorted((I / "graphs").iterdir()):
    cid = folder.name
    graph = g.Graph(cid)
    for s in [x for x in seeds.values() if x["cohort_id"] == cid]:
        c = g.Candidate.model_validate(s["seed_candidate"])
        a, b = s["positions"]
        c = c.model_copy(
            update={
                "new": c.new.model_copy(update={"tokens": graph.fs[a].tokens}),
                "existing": c.existing.model_copy(update={"tokens": graph.fs[b].tokens}),
            }
        )
        actual = {
            tuple(sorted((graph.pos[x.new.qualname], graph.pos[x.existing.qualname])))
            for x in graph.det.relatives([graph.fs[a]], [c])
        }
        seen = {
            tuple(r["pair"])
            for r in queues
            if r["seed_id"] == s["seed_id"] and r["method"] == "current_relatives_native"
        }
        assert actual == seen
        arms = collections.defaultdict(set)
        for r in queues:
            if r["seed_id"] == s["seed_id"]:
                arms[r["method"]].add(tuple(r["pair"]))
        for arm in arms.values():
            assert actual <= arm
        assert arms["spectral_overlap_ranking"] == arms["bounded_seed_diffusion"]
        count["native_seed_reexecutions"] += 1
    for r in [x for x in props if x["cohort_id"] == cid]:
        c = g.Candidate.model_validate(r["candidate"])
        q, t = r["query_position"], r["target_position"]
        assert c.new.code == graph.fs[q].code and c.existing.code == graph.fs[t].code
        assert r["source_body_sha256"] == [g.digest(graph.fs[q].code), g.digest(graph.fs[t].code)]
        assert not c.filtered and not r["reported"] and not r["blocking"] and not r["same_operation_confirmed"]
        count["source_complete_leads"] += 1
# Re-execute existing native after-refactor/copy controls under OUR write root.
import controls

# Existing control module star import omits this private constant.
controls._GENERIC = g._GENERIC
control_dir = H / "native-controls"
control_dir.mkdir(exist_ok=True)
g.HERE = control_dir
controls.HERE = control_dir
controls.main()
write(
    "NATIVE-VALIDATION.json",
    {
        "passed": True,
        "product_commit": PIN,
        "product_import": dry_lint.__file__,
        "product_modules": checked,
        "checks": dict(count),
        "cwd": str(pathlib.Path.cwd()),
        "provider_calls": 0,
    },
)
print(dict(count), len(checked), "pinned modules verified")
