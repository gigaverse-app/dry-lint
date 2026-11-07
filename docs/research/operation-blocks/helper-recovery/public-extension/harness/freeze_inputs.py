"""Snapshot only PR109 Python source; never inspect CI, credentials, or invoke providers."""

import subprocess

from common import HERE, PR, ROOT, dump, sha

REV = "73709fdbe884c107b665400a186cb71caecc03f7"


def main():
    paths = (
        subprocess.check_output(["git", "-C", str(PR), "ls-tree", "-r", "--name-only", REV, "--", "src/dry_lint"])
        .decode()
        .splitlines()
    )
    evidence = []
    for path in paths:
        if not path.endswith(".py"):
            continue
        body = subprocess.check_output(["git", "-C", str(PR), "show", REV + ":" + path])
        out = HERE / "frozen-pr109" / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)
        evidence.append(
            {
                "path": path,
                "sha256": sha(body),
                "bytes": len(body),
                "current_checkout_equal": (PR / path).read_bytes() == body,
            }
        )
    recipes = []
    for job, names in [
        ("improve-operation-blocks", ["helper_fallback_v1.py"]),
        ("improve-cpu-retrieval", ["harness.py", "views.py"]),
    ]:
        for name in names:
            src = ROOT / "jobs" / job / ".lab-results" / name
            body = src.read_bytes()
            out = HERE / name
            if out.exists():
                assert out.read_bytes() == body
            else:
                out.write_bytes(body)
            recipes.append({"source": str(src), "output": str(out), "sha256": sha(body), "bytes": len(body)})
    dump(HERE / "frozen-source-manifest.json", {"revision": REV, "files": evidence, "recipes": recipes})


if __name__ == "__main__":
    main()
