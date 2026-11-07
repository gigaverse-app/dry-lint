# Verification record

Verified locally on 2026-11-07. No provider calls, credential reads, network fetches, extra workers, or target-function execution were performed.

From the kit directory:

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 reproduce.py verify
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p test_kit.py -v
PYTHONDONTWRITEBYTECODE=1 python3 public_safety.py
python3 live.py --case JCTX-R2-08b01303638b8b9d --budget-usd .25
python3 hydrate.py
python3 kit.py inspect-case JCTX-R2-08b01303638b8b9d --kind claude --arm baseline --part answer
~~~

Results: all eight invariant tests pass; 88 recorded observations, 80 fresh calls, $0.70619572; 84 public request transformations match exactly. The live command is dry-run only: four requests, $0.11368560 frozen-rate reservation, zero calls. Hydrate with no flags is also dry-run only.

Native replay used Python 3.14.4 with the exact parser/model versions declared in README, loaded from existing read-only local package caches (no dependency downloads). Equivalent commands once that pinned environment is available:

~~~bash
PYTHONDONTWRITEBYTECODE=1 local-env/bin/python native.py --out local-native
PYTHONDONTWRITEBYTECODE=1 local-env/bin/python hydrate.py --git LOCAL_KAIZEN_GIT --out local-kaizen
~~~

Native result: 42 endpoint extractions and ten complete public R1 anchor extractions match; historical metadata differences are exposed, not rewritten. Kaizen result: source pin/file/function/Candidate hashes and all four exact wire hashes match. See native-verification.json. The local source-bearing Kaizen output and unpacked implementation directory were removed after checking; neither is part of the public kit. Network-fetch branches were not exercised.

A clean copied-directory check repeats the stdlib verify, unit tests, live dry-run and public-safety scan with no original lab paths on its import path. SHA256SUMS binds every public artifact except itself; INVENTORY.json records path, size and hash for every public artifact except itself and SHA256SUMS.

No repository-wide CI, product test suite, or dry-lint provider judging was run: this task only adds a self-contained lab evidence kit and explicitly forbids judge execution. The repository product implementation and CI are unchanged.

Limits: secret patterns cannot establish universal secrecy. Recorded response fields are allowlisted, decompressed archives scanned, source repositories pinned, licenses included, and the Kaizen source boundary is checked explicitly. Historical control serialization and future provider behavior remain the limitations described in README.
