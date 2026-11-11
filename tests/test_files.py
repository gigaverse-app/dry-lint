"""Repository files dry-lint writes keep the newline style they already have, on every platform."""

from pathlib import Path

import pytest

from dry_lint.feedback import Feedback
from dry_lint.files import encoded, write_text


@pytest.mark.parametrize("existing, expected", [
    (None, b"a\nb\n"),
    (b"x\ny\n", b"a\nb\n"),
    (b"x\r\ny\r\n", b"a\r\nb\r\n"),
    (b"x\r\ny\nz\n", b"a\nb\n"),  # mostly LF stays LF
    (b"x\r\ny\r\nz\n", b"a\r\nb\r\n"),  # mostly CRLF stays CRLF
])  # fmt: skip
def test_a_written_file_keeps_its_newline_style(tmp_path: Path, existing: bytes | None, expected: bytes) -> None:
    path = tmp_path / "README.md"
    if existing is not None:
        path.write_bytes(existing)
    write_text(path, "a\r\nb\n")  # text read in text mode, or built from parts, may carry either
    assert path.read_bytes() == expected


def test_feedback_keeps_a_crlf_checkout_crlf(tmp_path: Path) -> None:
    path = tmp_path / ".dry-lint-feedback.json"
    path.write_bytes(encoded(tmp_path / "absent", Feedback().model_dump_json(indent=2) + "\n").replace(b"\n", b"\r\n"))
    Feedback.read(path).write(path)
    data = path.read_bytes()
    assert b"\r\n" in data and data.count(b"\r\n") == data.count(b"\n")
