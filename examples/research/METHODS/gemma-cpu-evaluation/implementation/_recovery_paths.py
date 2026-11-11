"""Resolve explicitly supplied evidence roots; never infer a lab checkout."""

import os
from pathlib import Path


def recovery_path(relative=""):
    value = os.environ.get("DRY_LINT_EVIDENCE_ROOT")
    if not value:
        raise RuntimeError("Set DRY_LINT_EVIDENCE_ROOT to your materialized private evidence tree; see README.md")
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError("DRY_LINT_EVIDENCE_ROOT must be an existing directory")
    return str(root / relative)
