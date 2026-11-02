"""
A judge command for trying dry-lint without any model: it calls every candidate a duplicate.

    dry-lint check --judge command --judge-command "python examples/fake_judge.py"
"""

import json
import sys

prompt = sys.stdin.read()
print(json.dumps({"label": "duplicate", "score": 0.9, "owner": "existing", "why": f"{len(prompt)} characters read"}))
