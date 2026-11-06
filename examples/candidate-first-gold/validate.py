"""Offline source validation and frozen-background TF-IDF diagnostics. No target execution or APIs."""

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from dry_lint.bench import load_gold
from dry_lint.bench_background import BenchBackground
from dry_lint.extractors import PythonExtractor
from dry_lint.models import Candidate
from dry_lint.typescript import TypeScriptExtractor


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def local(root, value):
    path = (root / value).resolve()
    assert path.is_relative_to(root.resolve()) and path.is_file(), value
    return path


def source(root, ref):
    payload = json.loads(gzip.decompress(local(root, ref["source_file"]).read_bytes()))
    raw = payload["source"].encode()
    assert sha(raw) == payload["sha256"] == ref.get("file_sha256", ref.get("sha256"))
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert blob == payload["git_blob_sha1"]
    if "git_blob_sha1" in ref:
        assert blob == ref["git_blob_sha1"]
    return payload


def operation_checks(root, review, row):
    refs = {ref["path"]: ref for ref in review["source_closure"]}
    refs.update({row[k]["path"]: row[k] for k in ("new", "existing")})
    checked = []

    def regions(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ("source_operation_regions", "operation_regions", "exact_shared_or_contrasting_regions"):
                    for region in value:
                        yield key, region
                else:
                    yield from regions(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from regions(value)

    for key, region in regions(review["source_adjudication"]):
        path = region.get("path", region.get("source_id", "").split("::")[0])
        payload = source(root, refs[path])
        start, end = region["start_line"], region["end_line"]
        lines = payload["source"].splitlines(keepends=True)
        assert 1 <= start <= end <= len(lines), (row["id"], key)
        exact = "".join(lines[start - 1 : end])

        # Worker snippets may omit surrounding whitespace; coordinates remain exact.
        def normalize(text):
            return text.strip().removeprefix("export ").removeprefix("default ").removesuffix(";")

        assert normalize(exact) == normalize(region["code"]), (row["id"], key, start, end)
        for digest_key in ("sha256", "snippet_sha256", "region_sha256"):
            if digest_key in region:
                assert region[digest_key] in (sha(region["code"].encode()), sha(exact.encode())), (
                    row["id"],
                    digest_key,
                )

        checked.append(
            dict(
                path=path,
                source_file=refs[path]["source_file"],
                start_line=start,
                end_line=end,
                exact_sha256=sha(exact.encode()),
                evidence_sha256=sha(region["code"].encode()),
                evidence_key=key,
            )
        )
    return checked


def validate(root):
    if (root / "package-manifest.json").is_file():
        package = json.loads((root / "package-manifest.json").read_text())
        for entry in package["files"]:
            assert sha(local(root, entry["path"]).read_bytes()) == entry["sha256"], entry["path"]
    manifest = json.loads((root / "backgrounds/manifest.json").read_text())
    backgrounds = {}
    indexes = {}
    positions = {}
    for entry in manifest["backgrounds"]:
        raw = local(root, entry["path"]).read_bytes()
        assert sha(raw) == entry["sha256"]
        bg = BenchBackground.decode(raw)
        assert (bg.repository, bg.revision) == (entry["repository"], entry["revision"])
        assert bg.scope == entry["scope"] and bg.extraction_contract == entry["extraction_contract"]
        assert len(bg.documents) == entry["functions"] and bg.max_df == entry["max_df"]
        backgrounds[bg.repository] = bg
        indexes[bg.repository] = bg.index()
        pos = defaultdict(list)
        for i, doc in enumerate(bg.documents):
            pos[doc.id].append(i)
        positions[bg.repository] = pos
    accepted = rows(root / "accepted-public-gold.jsonl")
    disputed = rows(root / "disputed.jsonl")
    native = load_gold(root / "accepted-public-gold.jsonl")
    assert len(native) == len(accepted)
    for row, imported in zip(accepted, native, strict=True):
        assert imported.label == row["label"] and imported.new.code == row["new"]["code"]
        assert imported.existing.code == row["existing"]["code"]
    replay = []
    seen = set()
    sources_checked = set()
    sources_cache = {}
    for row in accepted + disputed:
        assert row["schema"] == 1 and row["whole_function_label"] is None
        repo, rev = row["repository"], row["revision"]
        bg = backgrounds[repo]
        assert rev == bg.revision == row["pins"]["snapshot"]
        candidate = Candidate.model_validate(row["candidate"])
        assert candidate.new.qualname != candidate.existing.qualname
        pair = (repo, tuple(sorted([candidate.new.qualname, candidate.existing.qualname])))
        assert pair not in seen
        seen.add(pair)
        review_path = local(root, row["review_file"])
        assert sha(review_path.read_bytes()) == row["review_file_sha256"]
        review = json.loads(review_path.read_text())
        assert review["coordinator_decision"]["label"] == row["label"]
        assert {r["reviewer"] for r in review["independent_provider_observations"]} == {"jev", "claude"}
        lic = source(root, row["license"])
        assert lic["source"] == row["license"]["text"]
        assert lic["revision"] == rev and lic["repository"] == repo
        for ref in review["source_closure"]:
            payload = source(root, ref)
            assert payload["revision"] == rev and payload["repository"] == repo and payload["path"] == ref["path"]
            sources_checked.add(ref["source_file"])
        fs = [candidate.new, candidate.existing]
        for key, f in zip(["new", "existing"], fs, strict=True):
            ref = row[key]
            payload = source(root, ref)
            assert (payload["repository"], payload["revision"], payload["path"]) == (repo, rev, f.path)
            cache_key = (repo, rev, f.path)
            if cache_key not in sources_cache:
                ex = PythonExtractor() if f.path.endswith(".py") else TypeScriptExtractor()
                ex.validate_source(f.path, payload["source"])
                sources_cache[cache_key] = ex.functions(f.path, payload["source"])
            matches = [x for x in sources_cache[cache_key] if x.qualname == f.qualname]
            assert len(matches) == 1 and matches[0].code == f.code == ref["code"]
            assert (f.line, f.end_line) == (ref["start_line"], ref["end_line"])
            assert sha(f.code.encode()) == ref["snippet_sha256"]
            pp = positions[repo][f.qualname]
            assert len(pp) == 1
            assert bg.documents[pp[0]].source_sha256 == ref["snippet_sha256"]
            sources_checked.add(ref["source_file"])
        regions = operation_checks(root, review, row)
        directions = []
        for direction, (query, target) in zip(
            ["new_to_existing", "existing_to_new"], [fs, list(reversed(fs))], strict=True
        ):
            qi, ti = positions[repo][query.qualname][0], positions[repo][target.qualname][0]
            scored = dict(indexes[repo].similar(bg.documents[qi].tokens(), exclude={qi}))
            # Explicit tie rule independent of posting insertion: descending score, ID, position.
            ranked = sorted(
                (i for i in range(len(bg.documents)) if i != qi),
                key=lambda i: (-scored.get(i, 0.0), bg.documents[i].id, i),
            )
            score = scored.get(ti, 0.0)
            rank = ranked.index(ti) + 1
            cross = [i for i in ranked if bg.documents[i].id.split("::")[0] != query.path]
            cross_rank = cross.index(ti) + 1 if ti in cross else None
            floor = 0.3 if query.lines < 6 else 0.5
            default_loss = (
                "same_file"
                if query.path == target.path
                else "score_floor"
                if score < floor
                else "top_k"
                if cross_rank > 3
                else None
            )
            balanced_loss = "score_floor" if score < 0.35 else "top_k" if rank > 20 else None
            directions.append(
                dict(
                    direction=direction,
                    query=query.qualname,
                    target=target.qualname,
                    score=score,
                    raw_rank=rank,
                    query_lines=query.lines,
                    query_token_count=sum(bg.documents[qi].counts.values()),
                    same_file=query.path == target.path,
                    cross_file_rank=cross_rank,
                    default_floor=floor,
                    default_loss=default_loss,
                    balanced_loss=balanced_loss,
                    raw_top1=rank <= 1,
                    raw_top3=rank <= 3,
                    default_retrieved=default_loss is None,
                    balanced_retrieved=balanced_loss is None,
                )
            )
        replay.append(
            dict(
                id=row["id"],
                repository=repo,
                family_id=row["family_id"],
                label=row["label"],
                active=row["active_panel_eligible"],
                operation_regions=regions,
                directions=directions,
            )
        )
    directional = {}
    for label in ("duplicate", "separate", "unknown", "borderline"):
        directional[label] = {}
        for direction in ("new_to_existing", "existing_to_new"):
            ds = [d for r in replay if r["label"] == label for d in r["directions"] if d["direction"] == direction]
            directional[label][direction] = {
                metric: {"numerator": sum(d[metric] for d in ds), "denominator": len(ds)}
                for metric in ("raw_top1", "raw_top3", "default_retrieved", "balanced_retrieved")
            }
    summary = {}
    for repo in backgrounds:
        summary[repo] = {}
        for label in ["duplicate", "separate"]:
            selected = [r for r in replay if r["repository"] == repo and r["active"] and r["label"] == label]
            ds = [d for r in selected for d in r["directions"]]
            summary[repo][label] = dict(
                pairs=len(selected),
                families=len({r["family_id"] for r in selected}),
                directional_denominator=len(ds),
                raw_top1=sum(d["raw_top1"] for d in ds),
                raw_top3=sum(d["raw_top3"] for d in ds),
                default_retrieved=sum(d["default_retrieved"] for d in ds),
                balanced_retrieved=sum(d["balanced_retrieved"] for d in ds),
                default_first_losses=dict(Counter(d["default_loss"] for d in ds if d["default_loss"])),
                default_floor_only_failures=sum(d["score"] < d["default_floor"] for d in ds),
                default_same_file_exclusions=sum(d["same_file"] for d in ds),
                small_query_directions=sum(d["query_lines"] < 6 for d in ds),
                balanced_first_losses=dict(Counter(d["balanced_loss"] for d in ds if d["balanced_loss"])),
            )
    return {
        "accepted_rows": len(accepted),
        "disputed_rows": len(disputed),
        "source_files_checked": len(sources_checked),
        "by_label_and_direction": directional,
        "by_repository_and_label": summary,
        "rows": replay,
        "settings": "Laboratory retrieval diagnostics only. Default .5 (.3 for <6 lines), top3 cross-file; balanced .35/top20 same-file allowed. No changed-line, rule, budget, cached judge, or reporting replay.",
        "tie_policy": "descending raw production score, source ID lexicographically, frozen document position; zero-score targets rank after positive scores",
        "self_and_missing": "Exact self document excluded. Selected IDs must each exist uniquely; missing or ambiguous endpoints fail validation.",
        "control_semantics": "Retrieving a separate control is exposure to a look-alike, not an emitted false positive.",
    }


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without -O: validation uses assertions.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.root)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
