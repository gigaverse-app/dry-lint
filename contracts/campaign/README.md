# Campaign contract

The discovery campaign ledger's rules, as a [Quint](https://quint.sh) model. The ledger
(`CampaignStore` in [discovery.py](../../src/dry_lint/discovery.py)) is the persisted record of what a
pull request or session has spent on paid judging. It admits a question only when it fits the budget, the
call caps and the exploration credit; it settles each reservation exactly once, charging the billed amount
or, when usage is unknown, keeping the reservation charged; and each new revision mints exploration credit
once, never above the exploration share of the budget. Recovery questions (residual pairs and operation
families) wait until every protected question on the revision is answered.

[pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect) generates histories from
[campaign.qnt](campaign.qnt). [conftest.py](conftest.py) replays each step against a real `CampaignStore`
on a temporary SQLite ledger and compares the ledger it reads back with the model's.

| Case | What it checks |
| --- | --- |
| 4 witnesses | credit minted once per revision; a second settle refused; residual recovery waiting for the protected pass; a family question needing an entered revision |
| 16 samples | seeded random histories of up to 10 steps mixing every action |
| 4 mutants | a ledger that settles a reservation twice, mints credit on every call, lets residual recovery skip the protected pass, or admits the same pair twice; each must be caught |
| coverage | every action reached |

```bash
uv sync --group quint
uv run pytest -c contracts/quint.ini contracts --quint-require-complete   # from the repository root; needs Node.js 22+
```

Money is in eighths of a dollar, so every amount is exact in Quint and in Python floats. The
[manifest](quint-connect.json) lists what the model leaves out: candidate ordering, concurrency between
processes, subscription judges and providers billing above their reservation. After editing the model, run
`uv run pytest-quint-connect codegen contracts/campaign/quint-connect.json` and commit the regenerated
[driver base](campaign_driver.py). Change the model only when the ledger's intended rules change.
