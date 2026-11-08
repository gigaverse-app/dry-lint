# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F401, I001
"""Read exact git config pins and project only detector/budget fields; no env/providers."""

import collections, hashlib, json, pathlib, subprocess, sys, tomllib
from inventory import HERE, BASE, jl, sha, write

sys.path.insert(0, str(BASE / "runtime/src"))
from dry_lint.settings import Settings

SAFE = [
    "preset",
    "include",
    "exclude",
    "neighbours",
    "comparer",
    "budget",
    "discovery",
    "report_at",
    "drop_below",
    "fail_at",
    "drift_at",
    "patterns",
]


def git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def main():
    panels = jl(BASE / "panels.jsonl")
    groups = collections.defaultdict(list)
    for p in panels:
        groups[(p["repository"], p["revision"])].append(p)
    rows = []
    for (repo, rev), ps in sorted(groups.items()):
        # Holdout config metadata can be checked; no source functions, labels or scores opened.
        roots = []
        for p in ps:
            m = json.loads(pathlib.Path(p["native_manifest_path"]).read_text())
            r = m.get("repository", {})
            if isinstance(r, dict) and r.get("git"):
                roots.append(r["git"])
        root = next((r for r in roots if git(r, "cat-file", "-t", rev) == "commit\n"), None)
        if not root:
            rows.append({"repository": repo, "revision": rev, "status": "missing_git_pin", "roots_attempted": roots})
            continue
        source = None
        raw = {}
        filehash = None
        for name in [".dry-lint.toml", "pyproject.toml"]:
            txt = git(root, "show", f"{rev}:{name}")
            if txt is None:
                continue
            data = tomllib.loads(txt)
            if name == "pyproject.toml":
                data = data.get("tool", {}).get("dry-lint", {})
            if data or name == ".dry-lint.toml":
                source = name
                raw = data
                filehash = hashlib.sha256(txt.encode()).hexdigest()
                break
        projected = {k: raw[k] for k in SAFE if k in raw}
        # Narrow projection excludes plugin credentials, URLs and environment bindings entirely.
        projected = {k: v for k, v in projected.items() if k not in ["comparer", "discovery"]}
        if isinstance(raw.get("comparer"), dict):
            projected["comparer"] = {
                k: v
                for k, v in raw["comparer"].items()
                if k in ["use", "min_similarity", "min_similarity_small", "max_df"]
            }
        elif isinstance(raw.get("comparer"), str):
            projected["comparer"] = raw["comparer"]
        if isinstance(raw.get("discovery"), dict):
            projected["discovery"] = {
                k: v
                for k, v in raw["discovery"].items()
                if k
                in [
                    "enabled",
                    "depth",
                    "min_similarity",
                    "calls_per_run",
                    "calls_per_function",
                    "baseline_calls",
                    "exploration_calls",
                    "usd_per_run",
                    "usd_per_function",
                ]
            }
        # Modern defaults are only a reference, never historic deployment inference.
        settings = Settings.model_validate(projected)
        scope = {"include": settings.include, "exclude": settings.exclude}
        scopes = [
            {
                "cohort_id": p["cohort_id"],
                "profiles": p["profiles"],
                "exact_list_match_to_config_or_current_defaults": p["scope"] == scope,
                "captured_scope": p["scope"],
            }
            for p in ps
        ]
        wf = []
        tree = git(root, "ls-tree", "-r", "--name-only", rev, ".github/workflows") or ""
        for name in tree.splitlines():
            txt = git(root, "show", f"{rev}:{name}") or ""
            # Store only action refs or fixed-valued relevant config lines. Never whole workflow secrets.
            matches = []
            for n, line in enumerate(txt.splitlines(), 1):
                s = line.strip()
                if "uses:" in s and ("gigaverse-app/dry-lint@" in s or "gigaverse-app/dry-lint/" in s):
                    matches.append({"line": n, "kind": "action_ref", "value": s.split("uses:", 1)[1].strip()})
            if matches:
                wf.append({"path": name, "sha256": hashlib.sha256(txt.encode()).hexdigest(), "action_refs": matches})
        rows.append(
            {
                "repository": repo,
                "revision": rev,
                "git_path": root,
                "status": "read_exact_pin",
                "configuration_source": source,
                "configuration_sha256": filehash,
                "declared_fields": projected,
                "modern_scope_projection": scope,
                "scope_comparisons": scopes,
                "workflow_evidence": wf,
                "shadow_budget_match": "explicit_same_usd"
                if (raw.get("budget") or {}).get("usd") == 0.04
                else "explicit_different_usd"
                if "usd" in (raw.get("budget") or {})
                else "not_declared",
                "shadow_preset_match": raw.get("preset") == "balanced",
                "judge_config_declared": bool(raw.get("judge")),
                "historical_changed_group_verified": False,
                "historical_cache_verified": False,
            }
        )
    write(HERE / "historical-configuration.jsonl", rows)
    summary = {
        "revisions": len(rows),
        "read_exact_pin": sum(r["status"] == "read_exact_pin" for r in rows),
        "declared_config_revisions": sum(bool(r.get("configuration_source")) for r in rows),
        "budget_evidence": dict(collections.Counter(r.get("shadow_budget_match", "unavailable") for r in rows)),
        "explicit_balanced": sum(r.get("shadow_preset_match", False) for r in rows),
        "scope_list_matches": sum(
            x["exact_list_match_to_config_or_current_defaults"] for r in rows for x in r.get("scope_comparisons", [])
        ),
        "scope_backgrounds": sum(len(r.get("scope_comparisons", [])) for r in rows),
        "workflow_dry_lint_refs": sum(bool(r.get("workflow_evidence")) for r in rows),
        "historical_changed_groups_verified": 0,
        "historical_caches_verified": 0,
        "conclusion": "The shadow balanced $0.04 single-query schedule is not authenticated historical behavior. Absent budget/preset declarations do not prove defaults deployed; workflows, CLI overrides, installed versions and credential availability remain outside this projection. Scope list inequality is evidence of differing specifications, not necessarily differing matched files.",
        "sources": [
            "historical-configuration.jsonl",
            str(BASE / "native_harness.py"),
            str(BASE / "runtime/src/dry_lint/settings.py"),
        ],
    }
    write(HERE / "CONFIGURATION-AUDIT.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
