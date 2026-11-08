import os
from pathlib import Path


def evidence_path(relative):
    return str(Path(os.environ["DRY_LINT_EVIDENCE_ROOT"]).resolve() / relative)


def runtime_path():
    return Path(os.environ["DRY_LINT_RUNTIME_ROOT"]).resolve()
