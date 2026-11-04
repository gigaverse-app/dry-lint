"""
INVARIANT: adopters bring their own keys. dry-lint never ships, holds, proxies or pays for an API key, a model, or
judge execution (docs/design.md#adopters-bring-their-own-keys). These tests fail when a change breaks that.
"""

import re
from pathlib import Path

import httpx
import pytest

from dry_lint import action
from dry_lint.ledger import RepositoryLedger

ROOT = Path(__file__).resolve().parent.parent
ADOPTER_KEYS = ("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN")
# Shapes of real credentials: Anthropic, Google, GitHub (classic and fine-grained), Slack, AWS, OpenAI.
CREDENTIAL = re.compile(r"sk-ant-[\w-]{10,}|AIza[\w-]{30,}|gh[pousr]_\w{30,}|github_pat_\w{20,}|xox[abpr]-[\w-]{10,}"
                        r"|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{32,}")


def action_inputs() -> dict[str, str]:
    """Each input of action.yml and its default, read from the `inputs:` block."""
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    block = text.split("\ninputs:\n", 1)[1].split("\noutputs:\n", 1)[0]
    inputs, current = {}, None
    for line in block.splitlines():
        if re.fullmatch(r"  [\w-]+:", line):
            current = line.strip().rstrip(":")
            inputs[current] = ""
        elif current and (default := re.fullmatch(r"    default: (.*)", line)):
            inputs[current] = default.group(1).strip().strip('"')
    return inputs


def test_no_action_input_defaults_to_a_credential_but_the_runs_own_github_token() -> None:
    inputs = action_inputs()
    credentials = {name: value for name, value in inputs.items() if re.search(r"key|token", name)}
    assert {"typesafe-api-key", "anthropic-api-key", "claude-code-oauth-token", "index-token", "github-token"} <= set(credentials)
    assert {name: value for name, value in credentials.items() if name != "github-token"} == dict.fromkeys(
        set(credentials) - {"github-token"}, "")
    assert credentials["github-token"] == "${{ github.token }}"


def test_the_action_never_reads_a_secret_of_its_own() -> None:
    assert "secrets." not in (ROOT / "action.yml").read_text(encoding="utf-8")


def test_no_credential_is_bundled_in_the_shipped_code_or_action() -> None:
    shipped = [ROOT / "action.yml", *sorted((ROOT / "src").rglob("*.py"))]
    found = {str(path.relative_to(ROOT)): CREDENTIAL.findall(path.read_text(encoding="utf-8")) for path in shipped}
    assert {path: hits for path, hits in found.items() if hits} == {}


@pytest.mark.parametrize("requested", ["auto", ""])
def test_without_the_adopters_keys_nothing_is_judged(requested: str) -> None:
    assert action.resolve_judge(requested, has_key=False) == "none"


def test_the_counter_receives_anonymous_counts_and_never_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ADOPTER_KEYS:
        monkeypatch.setenv(name, f"adopter-{name.lower()}")
    monkeypatch.delenv("INPUT_SHARE_TOTALS", raising=False)
    sent: list[httpx.Request] = []

    def counter(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    ledger = RepositoryLedger(repository="acme/shop", outbox=[{"repository": "0" * 64, "pull": 3, "kept_out": 1}])
    assert action.share(ledger, httpx.MockTransport(counter)) == 1
    [request] = sent
    assert "authorization" not in request.headers and "cookie" not in request.headers
    wire = str(request.url) + "".join(f"{k}:{v}" for k, v in request.headers.items()) + request.content.decode()
    assert not any(f"adopter-{name.lower()}" in wire for name in ADOPTER_KEYS)
