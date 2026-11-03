import runpy
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest

from dry_lint.bench import GoldFunction, GoldPair
from dry_lint.cli import main
from dry_lint.functions import behaviour_tokens, function_calls, structure_hash
from dry_lint.git import git
from dry_lint.models import Candidate, CandidatesFile, Function
from dry_lint.store import DirectoryStore, VerdictStore

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def run_script(monkeypatch: pytest.MonkeyPatch, name: str) -> dict:
    """An offline experiment script's globals, loaded with scripts/ importable, as it is when run."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return runpy.run_path(str(SCRIPTS / name))


def run_main(monkeypatch: pytest.MonkeyPatch, name: str, *args: str) -> None:
    """An offline experiment script run from the command line: `python scripts/<name> <args>`."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.setattr(sys, "argv", [name, *args])
    runpy.run_path(str(SCRIPTS / name), run_name="__main__")


def gold_line(new: str, existing: str, label: str) -> str:
    """One labelled pair, as a line of a `dry-lint bench` gold file."""
    pair = GoldPair(new=GoldFunction(id=new, code=""), existing=GoldFunction(id=existing, code=""), label=label)
    return pair.model_dump_json() + "\n"


EXISTING = '''
def shorten_text(text: str, limit: int) -> str:
    """Shorten text to at most `limit` characters, ending with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip()
    return cut.rstrip(".,;") + "…"
'''

TWIN = '''
def preview_caption_text(caption_text, max_len):
    if len(caption_text) <= max_len:
        return caption_text
    clipped = caption_text[: max_len - 1].rstrip()
    return clipped.rstrip(".,;") + "…"


def register_widget(registry, widget):
    registry.add(widget)
    registry.notify_listeners(widget.identifier)
    return widget
'''

FILLER_WORDS = [
    "invoice", "shipment", "warehouse", "customer", "payment", "refund", "coupon", "basket", "ledger", "tariff",
    "voucher", "parcel", "courier", "supplier", "receipt", "pallet", "carrier", "manifest", "rebate", "quota",
    "subscriber", "playlist", "thumbnail", "bitrate", "segment", "manifesto", "glacier", "harbor", "orchard", "prairie",
]  # fmt: skip


def filler_module() -> str:
    """Many unrelated functions, so the shared vocabulary of real look-alikes is rare enough to carry weight."""
    functions = []
    for i, word in enumerate(FILLER_WORDS):
        other = FILLER_WORDS[(i + 7) % len(FILLER_WORDS)]
        functions.append(
            f"def sync_{word}(store, {word}_id):\n"
            f"    record = store.load_{word}({word}_id)\n"
            f"    record.attach_{other}(store.fetch_{other}())\n"
            f"    return store.persist_{word}(record)\n"
        )
    return "\n\n".join(functions)


class Repo:
    """A throwaway git repository with a main branch, for running dry-lint the way a pull request would."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")

    def git(self, *args: str) -> str:
        return git(self.root, *args)

    def write(self, path: str, source: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source).lstrip())

    def commit(self, message: str = "change") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """main holds the existing helper and filler; the `feature` branch adds a re-implementation and a new function."""
    repo = Repo(tmp_path / "repo")
    repo.write("src/text.py", EXISTING)
    repo.write("src/filler.py", filler_module())
    repo.commit("main")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("src/widgets/caption.py", TWIN)
    repo.commit("feature")
    return repo


@pytest.fixture
def history(tmp_path: Path) -> Repo:
    """On main, oldest first: the helper and fillers; a twin of the helper; a docs-only change."""
    repo = Repo(tmp_path / "repo")
    repo.write("src/text.py", EXISTING)
    repo.write("src/filler.py", filler_module())
    repo.commit("helper")
    repo.write("src/widgets/caption.py", TWIN)
    repo.commit("twin")
    repo.write("README.md", "docs\n")
    repo.commit("docs")
    return repo


def function(path: str, source: str, name: str | None = None, owner: str | None = None) -> Function:
    """A function as the Python extractor and the detector would hand it on: with its tokens and its hash."""
    code = textwrap.dedent(source).strip()
    found = name or code.split("def ", 1)[1].split("(", 1)[0]
    plain = Function(path=path, name=found, owner=owner, line=1, end_line=len(code.splitlines()), code=code)
    return plain.model_copy(update={"hash": structure_hash(plain), "tokens": behaviour_tokens(plain),
                                    "calls": function_calls(plain)})


def replay_payload(api, *sources):
    return api["ReplayInput"].model_validate(
        {
            "steps": [
                {
                    "run_id": str(i),
                    "sources": {name: CandidatesFile(candidates=cs).model_dump() for name, cs in source.items()},
                }
                for i, source in enumerate(sources)
            ]
        }
    )


def coverage_pair(number: int = 1) -> Candidate:
    """Distinct pairs for scheduling and accounting experiments."""
    return Candidate(new=function("new.py", "def new(value):\n    return value"),
                     existing=function(f"existing{number}.py", f"def existing(value):\n    return value + {number}"),
                     similarity=0.9)


@pytest.fixture
def load_script(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], dict[str, Any]]:
    """Load an experiment's dynamic module namespace with its sibling imports available."""
    directory = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(directory))

    def load(name: str) -> dict[str, Any]:
        return runpy.run_path(str(directory / f"{name}.py"))

    return load


def claude(reply: dict, requests: list, *, status: int = 200) -> anthropic.DefaultHttpxClient:
    """A real SDK HTTP client whose transport answers every Messages call with `reply`."""
    def answer(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(status, json={"id": "msg_1", "type": "message", "role": "assistant",
                                             "model": "claude-sonnet-5-5", "stop_sequence": None,
                                             "usage": {"input_tokens": 900, "output_tokens": 120}, **reply})
    return anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(answer))


def judge_script(tmp_path: Path, score: float) -> str:
    """A judge command that scores the caption twin `score`, everything else 0.1, and counts its calls."""
    path, calls = tmp_path / "judge.py", tmp_path / "judge-calls"
    path.write_text(
        "import json, pathlib, sys\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        "with calls.open('a') as count:\n    count.write('.')\n"  # an append, so concurrent calls never lose a count
        "prompt = sys.stdin.read()\n"
        "twin = 'preview_caption_text' in prompt and 'shorten_text' in prompt\n"
        f"print(json.dumps({{'label': 'duplicate' if twin else 'separate', 'score': {score} if twin else 0.1, "
        "'owner': 'existing', 'why': 'both shorten text with an ellipsis'}))\n"
    )
    return f'"{sys.executable}" "{path}"'


@pytest.fixture
def twin_judge(tmp_path: Path) -> str:
    """Judges the caption twin a reported duplicate (0.85): blocking by default, a warning when fail_at is raised."""
    return judge_script(tmp_path, 0.85)


@pytest.fixture
def blocking_twin_judge(tmp_path: Path) -> str:
    """Judges the caption twin a duplicate (0.95) that blocks even with a raised fail_at."""
    return judge_script(tmp_path, 0.95)


def run_cli(repo: Repo, tmp_path: Path, *args: str, command: str = "check") -> int:
    """The dry-lint command on `repo`, with a verdict store of its own under `tmp_path`."""
    return main([command, "--root", str(repo.root), "--store", str(tmp_path / "store"), *args])


def judge_calls(tmp_path: Path) -> int:
    """How many pairs the `twin_judge` command has been asked about."""
    path = tmp_path / "judge-calls"
    return len(path.read_text()) if path.exists() else 0


@pytest.fixture
def store(tmp_path: Path) -> VerdictStore:
    return VerdictStore(DirectoryStore(tmp_path / "verdicts"))
