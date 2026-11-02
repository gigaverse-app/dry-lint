import subprocess
import textwrap
from pathlib import Path

import pytest

from dry_lint.functions import Function

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
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout

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
    code = textwrap.dedent(source).strip()
    found = name or code.split("def ", 1)[1].split("(", 1)[0]
    return Function(path=path, name=found, owner=owner, line=1, end_line=len(code.splitlines()), code=code)
