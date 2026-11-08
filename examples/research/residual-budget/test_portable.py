"""Relocation and corruption invariants for the frozen-candidate corpus."""

import hashlib
import json
from pathlib import Path

import pytest
from replay_frozen import Corpus


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "objects").mkdir()
    data = b'{"immutable": true}'
    digest = hashlib.sha256(data).hexdigest()
    (tmp_path / "objects" / (digest + ".json")).write_bytes(data)
    old_path = "/unavailable/original/observation.json"
    (tmp_path / "manifest.json").write_text(json.dumps({"schema": 1, "original_receipt_locations": {old_path: digest}}))
    return Corpus(tmp_path), old_path, digest


def test_original_receipt_resolves_only_from_relocated_corpus(corpus):
    bundle, old_path, digest = corpus
    assert not Path(old_path).exists()
    assert json.loads(bundle.original(old_path, digest).read_text()) == {"immutable": True}


def test_changed_original_bytes_are_rejected(corpus):
    bundle, old_path, digest = corpus
    bundle.path(digest).write_text('{"immutable": false}')
    with pytest.raises(AssertionError, match="Corrupt corpus"):
        bundle.original(old_path, digest)


def test_missing_corpus_object_never_falls_back_to_old_path(corpus):
    bundle, old_path, digest = corpus
    bundle.path(digest).unlink()
    with pytest.raises(FileNotFoundError):
        bundle.original(old_path, digest)


@pytest.mark.parametrize("digest", ["../manifest", "0" * 63, "0" * 65])
def test_object_references_cannot_escape_content_addressed_store(corpus, digest):
    bundle, _, _ = corpus
    with pytest.raises(AssertionError, match="Invalid object digest"):
        bundle.path(digest)
