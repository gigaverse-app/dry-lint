"""Files dry-lint writes into the adopter's repository, in the newline style each file already uses."""

from pathlib import Path


def encoded(path: Path, text: str) -> bytes:
    """
    `text` as UTF-8 with the newlines `path` already uses: CRLF if most of its lines end that way, LF otherwise and
    for a new file. Writing through Python's text mode would turn every LF into CRLF on Windows, rewriting each line
    of an LF README and leaving a diff that is all line endings.
    """
    newline = "\n"
    if path.exists():
        data = path.read_bytes()
        crlf = data.count(b"\r\n")
        if crlf and crlf >= data.count(b"\n") - crlf:
            newline = "\r\n"
    return text.replace("\r\n", "\n").replace("\n", newline).encode("utf-8")


def write_text(path: Path, text: str) -> None:
    """Write a repository file, keeping its newline style."""
    path.write_bytes(encoded(path, text))
