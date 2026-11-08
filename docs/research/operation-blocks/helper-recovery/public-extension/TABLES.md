# Separate background result tables

Funded pair/background units; original inherited labels and scopes remain separate. No cross-scope recall rate is computed.

| Repository | Revision | Scope | Label | Pair units | Blocks original → helper | CPU original → fallback |
|---|---|---|---|---|---|---|
| due | 33857688 | configured | duplicate | 3 | 3 → 3 | 3 → 3 |
| due | 33857688 | configured | separate | 6 | 0 → 0 | 2 → 2 |
| due | 33857688 | diagnostic,original-due | duplicate | 3 | 3 → 3 | 3 → 3 |
| due | 33857688 | diagnostic,original-due | separate | 6 | 0 → 0 | 1 → 1 |
| due | 6a681317 | configured | duplicate | 4 | 2 → 2 | 2 → 2 |
| due | 6a681317 | configured | separate | 1 | 0 → 0 | 0 → 0 |
| due | 6a681317 | diagnostic,original-due | duplicate | 4 | 2 → 2 | 2 → 2 |
| due | 6a681317 | diagnostic,original-due | separate | 1 | 0 → 0 | 0 → 0 |
| due | 701d2167 | configured | separate | 2 | 0 → 0 | 0 → 0 |
| due | 701d2167 | diagnostic,original-due | separate | 2 | 0 → 0 | 0 → 0 |
| due | 8d4d100b | configured | duplicate | 3 | 3 → 3 | 3 → 3 |
| due | 8d4d100b | configured | separate | 7 | 1 → 1 | 2 → 2 |
| due | 8d4d100b | diagnostic,original-due | duplicate | 3 | 3 → 3 | 3 → 3 |
| due | 8d4d100b | diagnostic,original-due | separate | 7 | 1 → 1 | 2 → 2 |
| due | d45977a8 | configured | separate | 4 | 1 → 1 | 1 → 1 |
| due | d45977a8 | diagnostic,original-due | separate | 4 | 1 → 1 | 1 → 1 |
| pytest-obligation | 389c5bb8 | original-pytest-obligation | separate | 4 | 2 → 2 | 4 → 4 |
| pytest-obligation | d39f77ea | original-pytest-obligation | borderline | 3 | 3 → 3 | 3 → 3 |
| pytest-obligation | d39f77ea | original-pytest-obligation | duplicate | 6 | 6 → 6 | 6 → 6 |
| pytest-obligation | d39f77ea | original-pytest-obligation | separate | 2 | 2 → 2 | 2 → 2 |
| pytest-selective | 4ab22f35 | legacy,original-pytest-selective | separate | 4 | 3 → 3 | 3 → 3 |
| pytest-selective | ae130637 | legacy,original-pytest-selective | duplicate | 8 | 7 → 7 | 8 → 8 |

## Score floors and same-file context

Counts below are directional units after lineage deduplication within a background. `Below q floor` independently counts sparse scores below 0.3 for queries under six lines and below 0.5 otherwise. `Below .35` uses the wide route floor. `Same file` is another independent attribute: columns can overlap and are not an additive failure decomposition. Raw-rank bands and exclusive first-loss counts are in the machine table. No extra size-ratio filter is applied.

| Repository | Revision | Scope | Label | Directions | Below q floor | Below .35 | Same file | TF-IDF3 funded | Wide funded | Original CPU funded |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| due | 33857688 | configured | duplicate | 6 | 0 | 0 | 2 | 4 | 6 | 6 |
| due | 33857688 | configured | separate | 12 | 12 | 12 | 0 | 0 | 0 | 2 |
| due | 33857688 | diagnostic,original-due | duplicate | 6 | 0 | 0 | 2 | 4 | 6 | 6 |
| due | 33857688 | diagnostic,original-due | separate | 12 | 12 | 12 | 0 | 0 | 0 | 1 |
| due | 6a681317 | configured | duplicate | 8 | 6 | 4 | 2 | 2 | 4 | 4 |
| due | 6a681317 | configured | separate | 2 | 2 | 2 | 0 | 0 | 0 | 0 |
| due | 6a681317 | diagnostic,original-due | duplicate | 8 | 6 | 4 | 2 | 2 | 4 | 4 |
| due | 6a681317 | diagnostic,original-due | separate | 2 | 2 | 2 | 0 | 0 | 0 | 0 |
| due | 701d2167 | configured | separate | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| due | 701d2167 | diagnostic,original-due | separate | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| due | 8d4d100b | configured | duplicate | 6 | 0 | 0 | 0 | 6 | 6 | 6 |
| due | 8d4d100b | configured | separate | 14 | 12 | 12 | 2 | 0 | 2 | 3 |
| due | 8d4d100b | diagnostic,original-due | duplicate | 6 | 0 | 0 | 0 | 6 | 6 | 6 |
| due | 8d4d100b | diagnostic,original-due | separate | 14 | 12 | 12 | 2 | 0 | 2 | 3 |
| due | d45977a8 | configured | separate | 8 | 8 | 6 | 0 | 0 | 2 | 2 |
| due | d45977a8 | diagnostic,original-due | separate | 8 | 8 | 6 | 0 | 0 | 2 | 2 |
| pytest-obligation | 389c5bb8 | original-pytest-obligation | separate | 8 | 4 | 4 | 0 | 4 | 4 | 6 |
| pytest-obligation | d39f77ea | original-pytest-obligation | borderline | 6 | 0 | 2 | 0 | 6 | 6 | 6 |
| pytest-obligation | d39f77ea | original-pytest-obligation | duplicate | 12 | 0 | 0 | 0 | 12 | 12 | 12 |
| pytest-obligation | d39f77ea | original-pytest-obligation | separate | 4 | 1 | 0 | 0 | 2 | 4 | 4 |
| pytest-selective | 4ab22f35 | legacy,original-pytest-selective | separate | 8 | 4 | 6 | 2 | 3 | 4 | 5 |
| pytest-selective | ae130637 | legacy,original-pytest-selective | duplicate | 16 | 3 | 2 | 0 | 13 | 14 | 16 |

Machine sources: [pair results](expected/regression-table.jsonl), [floor/same-file CSV](expected/floor-samefile.csv), [all directional outcomes](expected/direction-table.jsonl), [all stage counts](expected/stage-counts.jsonl). Run `python3 -I replay.py --out replayed --verify` to recompute them from the recordings.
