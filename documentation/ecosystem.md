---
title: Related tools
description: Choose dry-lint, pytest-selective, CI-esta, Due, pytest-obligation or pytest-quint-connect for the problem you need to solve.
---

# Choose the tool for your problem

| Your problem | Tool | What you gain |
| --- | --- | --- |
| Pull requests re-implement functions the codebase already has | [dry-lint](https://dry-lint.readthedocs.io/en/latest/) | Judged duplicate findings on each pull request and a ratcheted backlog |
| Every edit reruns unrelated Python tests | [pytest-selective](https://pytest-selective.readthedocs.io/en/latest/) | Explained affected-test selection or complete-lane routing, with conservative fallbacks |
| CI is slow and you need to know why | [CI-esta](https://ci-esta.readthedocs.io/en/latest/) | Job and step reports, dependency critical paths and an honest required gate |
| Background work can be lost or repeated after a crash | [Due](https://due.readthedocs.io/en/latest/) | Durable Django work tables, recovery, and explicit completion evidence |
| Passing tests miss failures during retries or recovery | [pytest-obligation](https://pytest-obligation.readthedocs.io/en/latest/) | Executable crash histories, fault scenarios, and checks for declared guarantees |
| Your Python code should match a formal model | [pytest-quint-connect](https://pytest-quint-connect.readthedocs.io/en/latest/) | Quint-generated histories replayed against your implementation under pytest |

Each of these projects runs dry-lint on its own pull requests, and the
[case studies](../docs/case-studies/pytest-selective.md) report what that cleanup found.
