"""What GitHub Actions tells a run about itself."""

import json
import os
from pathlib import Path


def github_event() -> dict:
    """The triggering event's payload (GITHUB_EVENT_PATH), or {} outside GitHub Actions."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    return json.loads(Path(path).read_text()) if path and Path(path).exists() else {}
