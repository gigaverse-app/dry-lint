import sys
import textwrap
from pathlib import Path

import pytest

from dry_lint.functions import behaviour_tokens, function_calls, structure_hash
from dry_lint.git import git
from dry_lint.models import Function
from dry_lint.store import DirectoryStore, VerdictStore

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


def function(path: str, source: str, name: str | None = None, owner: str | None = None) -> Function:
    """A function as the Python extractor and the detector would hand it on: with its tokens and its hash."""
    code = textwrap.dedent(source).strip()
    found = name or code.split("def ", 1)[1].split("(", 1)[0]
    plain = Function(path=path, name=found, owner=owner, line=1, end_line=len(code.splitlines()), code=code)
    return plain.model_copy(update={"hash": structure_hash(plain), "tokens": behaviour_tokens(plain),
                                    "calls": function_calls(plain)})


@pytest.fixture
def twin_judge(tmp_path: Path) -> str:
    """A judge command that calls the caption twin a duplicate, everything else separate, and counts its calls."""
    path, calls = tmp_path / "judge.py", tmp_path / "judge-calls"
    path.write_text(
        "import json, pathlib, sys\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        "calls.write_text(str(int(calls.read_text()) + 1) if calls.exists() else '1')\n"
        "prompt = sys.stdin.read()\n"
        "twin = 'preview_caption_text' in prompt and 'shorten_text' in prompt\n"
        "print(json.dumps({'label': 'duplicate' if twin else 'separate', 'score': 0.9 if twin else 0.1, "
        "'owner': 'existing', 'why': 'both shorten text with an ellipsis'}))\n"
    )
    return f'"{sys.executable}" "{path}"'


def judge_calls(tmp_path: Path) -> int:
    """How many pairs the `twin_judge` command has been asked about."""
    path = tmp_path / "judge-calls"
    return int(path.read_text()) if path.exists() else 0


@pytest.fixture
def store(tmp_path: Path) -> VerdictStore:
    return VerdictStore(DirectoryStore(tmp_path / "verdicts"))
