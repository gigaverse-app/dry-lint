import io
import json
from pathlib import Path

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.models import Candidate, Run, Verdict, pair_key
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, Record, S3Store, VerdictStore

from conftest import function

NEW = function(
    "new.py", "def clip(text, n):\n    if len(text) <= n:\n        return text\n    return text[: n - 1] + '…'\n"
)
OLD = function(
    "old.py",
    "def shorten(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[: limit - 1] + '…'\n",
)


def verdict(label: str, score: float = 0.9, judge: str = "jev", version: str = "reuse-v2") -> Verdict:
    return Verdict(label=label, score=score, owner="existing", judge=judge, judge_version=version)


def candidate(new=NEW, old=OLD, similarity: float = 0.7, comparer: str = "tfidf:1") -> Candidate:
    return Candidate(new=new, existing=old, similarity=similarity, comparer=comparer, similarity_reusable=True)


def edited(f, before: str, after: str):
    """The function after an edit, rehashed as the detector would."""
    return function(f.path, f.code.replace(before, after))


def lookup(store: VerdictStore, pair: Candidate, judge: str = "jev", version: str | None = None) -> Verdict | None:
    return store.lookup(pair, judge, reopen_margin=0.05, version=version).verdict


@pytest.mark.parametrize("label", ["duplicate", "drifted", "separate"])
def test_a_verdict_is_reused_while_neither_function_changes_logic(store: VerdictStore, label: str) -> None:
    store.remember(candidate(), verdict(label))
    cosmetic = edited(NEW, "return text\n", "return text  # unchanged\n")
    result = store.lookup(candidate(new=cosmetic, similarity=0.95), "jev", reopen_margin=0.05)
    assert result.verdict == verdict(label) and result.why == "neither function's logic changed"


@pytest.mark.parametrize("label", ["duplicate", "drifted"])
def test_a_duplicate_verdict_reopens_on_any_logic_change(store: VerdictStore, label: str) -> None:
    store.remember(candidate(), verdict(label))
    changed = edited(NEW, "n - 1", "n - 2")
    assert lookup(store, candidate(new=changed, similarity=0.5)) is None


def test_a_separate_verdict_survives_logic_changes_that_do_not_bring_the_pair_closer(store: VerdictStore) -> None:
    store.remember(candidate(similarity=0.7), verdict("separate", 0.2))
    changed = edited(OLD, "limit - 1", "limit - 2")
    assert lookup(store, candidate(old=changed, similarity=0.74)) == verdict("separate", 0.2)
    closer = store.lookup(candidate(old=changed, similarity=0.76), "jev", reopen_margin=0.05)
    assert closer.verdict is None and "now 0.76" in closer.why


def test_a_separate_verdict_reopens_when_a_literal_makes_the_pair_one_concept(store: VerdictStore) -> None:
    """
    INVARIANT: a "separate" verdict is reused after a logic change only when the comparer can see that change. TF-IDF
    tokens leave out literals, so an edit that makes two functions identical can leave their similarity unchanged.
    """
    extractor = PythonExtractor()
    [peer] = extractor.functions("users.py", "def is_active(user):\n    return user.status == 'active'\n")
    [before] = extractor.functions("admin.py", "def is_enabled(user):\n    return user.status == 'disabled'\n")
    [after] = extractor.functions("admin.py", "def is_enabled(user):\n    return user.status == 'active'\n")

    def pair(new):
        detector = Detector([peer, new], Settings(), TfidfComparer(), [extractor])
        return detector.pair(detector.hashed(new), peer, detector.comparer.similarity(new, peer))

    store.remember(pair(before), verdict("separate", 0.2))
    assert pair(after).similarity == pair(before).similarity  # the comparer cannot see the edit
    assert lookup(store, pair(after)) is None


@pytest.mark.parametrize("comparer", ["embedding:1", "tfidf:2"])
def test_similarities_from_another_comparer_are_not_compared(store: VerdictStore, comparer: str) -> None:
    store.remember(candidate(similarity=0.9, comparer="tfidf:1"), verdict("separate", 0.2))
    changed = edited(OLD, "limit - 1", "limit - 2")
    assert lookup(store, candidate(old=changed, similarity=0.1, comparer=comparer)) is None
    unchanged = lookup(store, candidate(similarity=0.1, comparer=comparer))
    assert unchanged == verdict("separate", 0.2)  # same logic: the answer holds whatever measured it


def test_a_verdict_from_another_judge_is_not_reused(store: VerdictStore) -> None:
    store.remember(candidate(), verdict("duplicate", judge="command:claude", version="1"))
    result = store.lookup(candidate(), "jev", reopen_margin=0.05)
    assert result.verdict is None and result.why == "judged by command:claude, not jev"


def test_an_older_version_of_the_same_judge_is_reused_unless_a_version_is_required(store: VerdictStore) -> None:
    store.remember(candidate(), verdict("duplicate", version="reuse-v1"))
    assert lookup(store, candidate()) == verdict("duplicate", version="reuse-v1")
    assert lookup(store, candidate(), version="reuse-v2") is None
    assert lookup(store, candidate(), version="reuse-v1") == verdict("duplicate", version="reuse-v1")


OPUS, BAND = "anthropic:dry-v1:claude-opus-5-5", (0.5, 0.91)


@pytest.mark.parametrize(
    "stored,escalation,reused",
    [
        (0.7, None, True),  # Jev's own answer, for Jev alone
        (0.7, OPUS, False),  # an in-band answer the second judge never saw: jev, then jev+opus
        (0.95, OPUS, True),  # above the band, the second judge would not have been asked
        (0.2, OPUS, True),  # below it, neither
    ],
)
def test_a_first_answer_holds_only_where_this_judging_would_not_have_asked_a_second_judge(
    store: VerdictStore, stored: float, escalation: str | None, reused: bool
) -> None:
    store.remember(candidate(), verdict("duplicate", score=stored))
    assert (store.lookup(candidate(), "jev", 0.05, escalation=escalation, band=BAND).verdict is not None) is reused


@pytest.mark.parametrize(
    "escalation,reused",
    [
        (OPUS, True),
        ("anthropic:dry-v1:claude-sonnet-5-5", False),
        ("anthropic:dry-v2:claude-opus-5-5", False),
        (None, False),  # Jev alone measures its thresholds on its own scores, not Opus's
    ],
)
def test_a_second_opinion_holds_only_for_the_same_second_judge(
    store: VerdictStore, escalation: str | None, reused: bool
) -> None:
    store.remember(candidate(), verdict("duplicate", score=0.9).model_copy(update={"second_opinion": OPUS}))
    result = store.lookup(candidate(), "jev", 0.05, escalation=escalation, band=BAND)
    assert (result.verdict is not None) is reused
    assert reused or result.why.startswith(f"second opinion from {OPUS}")


def test_the_store_is_keyed_on_the_unordered_pair(store: VerdictStore) -> None:
    store.remember(candidate(), verdict("duplicate"))
    swapped = Candidate(new=OLD, existing=NEW, similarity=0.7, comparer="tfidf:1")
    assert lookup(store, swapped) == verdict("duplicate")
    assert candidate().key == swapped.key == pair_key("old.py::shorten", "new.py::clip")


def test_unknown_pairs_have_no_verdict(store: VerdictStore) -> None:
    assert store.lookup(candidate(), "jev", reopen_margin=0.05) == (None, "never judged")


def test_lossy_comparers_require_unchanged_hashes_even_with_an_unchanged_score(store: VerdictStore) -> None:
    before = candidate(comparer="dryer:1").model_copy(update={"similarity_reusable": False})
    store.remember(before, verdict("separate"))
    assert lookup(store, before) == verdict("separate")
    after = before.model_copy(update={"new": edited(NEW, "n - 1", "n - 2")})
    result = store.lookup(after, "jev", 0.05)
    assert result.verdict is None and "exact-hash" in result.why


def test_schema_one_records_still_load_with_conservative_similarity_reuse(store: VerdictStore) -> None:
    record = store.remember(candidate(), verdict("separate")).model_dump()
    record["schema"] = 1
    del record["similarity_reusable"]
    store.backend.put(candidate().key, json.dumps(record).encode())
    assert lookup(store, candidate()) == verdict("separate")
    changed = candidate(new=edited(NEW, "n - 1", "n - 2"))
    assert lookup(store, changed) is None


def test_each_record_is_its_own_file_holding_hashes_and_never_code(store: VerdictStore, tmp_path: Path) -> None:
    source = Run(repository="o/r", pull_request=7, head="abc")
    store.remember(candidate(), verdict("drifted"), source)
    [path] = (tmp_path / "verdicts").iterdir()
    assert path.name == f"{candidate().key}.json"
    data = json.loads(path.read_text())
    assert data["schema"] == 14 and data["pair"] == ["new.py::clip", "old.py::shorten"]
    assert data["hashes"] == [NEW.hash, OLD.hash] and data["comparer"] == "tfidf:1" and data["similarity"] == 0.7
    assert data["source"]["pull_request"] == 7 and "code" not in path.read_text()
    assert [r.verdict.label for r in store.records()] == ["drifted"]


def test_a_new_answer_replaces_the_old_record(store: VerdictStore) -> None:
    store.remember(candidate(), verdict("duplicate"))
    store.remember(candidate(), verdict("separate", 0.1))
    assert [r.verdict.label for r in store.records()] == ["separate"]


def test_an_empty_or_missing_folder_has_no_records(tmp_path: Path) -> None:
    assert list(VerdictStore(DirectoryStore(tmp_path / "missing")).records()) == []
    (tmp_path / "empty").mkdir()
    assert list(DirectoryStore(tmp_path / "empty").keys()) == []


def test_records_skip_keys_that_vanish_while_listing(tmp_path: Path) -> None:
    class Racing(DirectoryStore):
        def get(self, key: str) -> bytes | None:
            return None

    folder = DirectoryStore(tmp_path / "v")
    folder.put("abc", b"{}")
    assert list(VerdictStore(Racing(tmp_path / "v")).records()) == []


@pytest.fixture
def s3() -> tuple[S3Store, Stubber]:
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
    return S3Store("s3://bucket/dry-lint/repo", client=client), Stubber(client)


def body(data: bytes) -> StreamingBody:
    return StreamingBody(io.BytesIO(data), len(data))


def test_the_s3_store_reads_writes_and_lists_objects_under_its_prefix(s3) -> None:
    store, stub = s3
    record = (
        Record(
            key="k1",
            pair=("a", "b"),
            hashes=("1", "2"),
            comparer="tfidf:1",
            similarity=0.5,
            verdict=verdict("duplicate"),
        )
        .model_dump_json()
        .encode()
    )
    stub.add_response(
        "put_object",
        {},
        {"Bucket": "bucket", "Key": "dry-lint/repo/k1.json", "Body": record, "ContentType": "application/json"},
    )
    stub.add_response("get_object", {"Body": body(record)}, {"Bucket": "bucket", "Key": "dry-lint/repo/k1.json"})
    stub.add_client_error(
        "get_object",
        service_error_code="NoSuchKey",
        http_status_code=404,
        expected_params={"Bucket": "bucket", "Key": "dry-lint/repo/k2.json"},
    )
    stub.add_response(
        "list_objects_v2",
        {
            "Contents": [
                {"Key": "dry-lint/repo/k1.json"},
                {"Key": "dry-lint/repo/old/x.json"},
                {"Key": "dry-lint/repo/notes.txt"},
            ],
            "IsTruncated": False,
        },
        {"Bucket": "bucket", "Prefix": "dry-lint/repo/"},
    )
    with stub:
        store.put("k1", record)
        assert store.get("k1") == record
        assert store.get("k2") is None
        assert list(store.keys()) == ["k1"]
    stub.assert_no_pending_responses()


def test_the_s3_store_needs_an_s3_uri_and_accepts_a_bare_bucket() -> None:
    with pytest.raises(ValueError, match="s3://"):
        S3Store("gs://bucket/x", client=object())
    bare = S3Store("s3://bucket", client=object())
    assert (bare.bucket, bare.prefix) == ("bucket", "")
    assert S3Store("s3://bucket/a/", client=object()).prefix == "a/"


def test_the_s3_store_makes_its_own_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    assert S3Store("s3://bucket/x").client.meta.service_model.service_name == "s3"


def test_spending_accumulates_per_pull_request_and_is_not_a_verdict(store: VerdictStore) -> None:
    pull, other = Run(repository="o/r", pull_request=7), Run(repository="o/r", pull_request=8)
    store.add_spent(pull, 0.01)
    store.add_spent(pull, 0.02)
    store.add_spent(other, 0.005)
    assert store.spent(pull) == pytest.approx(0.03) and store.spent(other) == pytest.approx(0.005)
    store.remember(candidate(), verdict("separate"))
    assert [r.key for r in store.records()] == [candidate().key]  # spending is never read as a verdict


def test_spending_outside_a_pull_request_or_of_nothing_is_not_kept(store: VerdictStore) -> None:
    pull = Run(repository="o/r", pull_request=7)
    store.add_spent(None, 0.01)
    store.add_spent(Run(repository="o/r", head="abc"), 0.01)
    store.add_spent(pull, 0.0)
    assert store.spent(None) == store.spent(Run(repository="o/r")) == store.spent(pull) == 0.0
    assert list(store.backend.keys()) == []
