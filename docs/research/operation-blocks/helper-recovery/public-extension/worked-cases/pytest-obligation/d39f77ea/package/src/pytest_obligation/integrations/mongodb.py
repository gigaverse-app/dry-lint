"""Interrupt acknowledged MongoDB writes on one PyMongo client (or Motor's delegate).

Observe the driver's wire-command boundary, not collection methods or command
monitoring callbacks (PyMongo swallows exceptions from monitoring listeners).
Single-document writes and each bulk wire batch count after acknowledgement;
transactional writes count only at commitTransaction. Reads and aborts do not
count. Unknown commands conservatively count as writes. Unacknowledged writes
are refused: there is no acknowledged boundary at which to kill the worker.

The checkout scope follows Motor into its executor thread. All operations on
the selected client are fenced after death, including reads and finally-block
writes. Other clients remain usable by independent provider/observer code.
PyMongo 4.18 moved bulk batches from Connection.write_command/unack_write to
command_runner.run_bulk_write_command (imported by name into bulk.py and
client_bulk.py), and read checkouts from MongoClient._checkout to
_conn_from_server; each boundary is patched where the installed driver has it.

This integration supports synchronous PyMongo 4.9-4.18 and Motor 3.7+ via .delegate;
native AsyncMongoClient requires a separate async wire adapter. It neither
freezes server TTLs nor claims Kafka delivery coverage. Find-query inspection
is supplied separately by mongodb_selection and enabled by mongodb_host.
"""

from collections.abc import Callable, Collection, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from typing import Any

from pytest_obligation.host import Host
from pytest_obligation.models import ObligationContractDesignError
from pytest_obligation.worker_death import CommitWorker, LostCommitReplies

# Anything not positively known to be read-only counts conservatively. Aggregation
# has its own rule because $out/$merge are writes despite using a read-shaped API.
_READ_COMMANDS = frozenset(
    {
        "find",
        "getMore",
        "killCursors",
        "count",
        "distinct",
        "ping",
        "hello",
        "isMaster",
        "ismaster",
        "listCollections",
        "listIndexes",
        "listDatabases",
        "explain",
        "collStats",
        "dbStats",
        "abortTransaction",
    }
)


def _writes(spec: dict[str, Any]) -> bool:
    name = next(iter(spec))
    if name == "aggregate":
        return any("$out" in stage or "$merge" in stage for stage in spec.get("pipeline", ()))
    return name not in _READ_COMMANDS


@contextmanager
def _watching(client: Any, before: Callable[[], None], committed: Callable[[], None]) -> Iterator[None]:
    import pymongo
    import pytest
    from pymongo.synchronous import bulk, client_bulk
    from pymongo.synchronous.bulk import _Bulk
    from pymongo.synchronous.mongo_client import MongoClient
    from pymongo.synchronous.pool import Connection

    if not isinstance(client, MongoClient):
        raise ObligationContractDesignError("pass a synchronous PyMongo client, or Motor client.delegate")
    # A separate context per watcher lets the killer and reply breaker compose.
    active: ContextVar[tuple[bool, Any]] = ContextVar("mongodb_checkout", default=(False, None))
    original_command = Connection.command
    original_send = Connection.send_message
    original_bulk_unack = _Bulk.execute_no_results

    def fenced(original: Callable[..., AbstractContextManager[Any]]) -> Callable[..., AbstractContextManager[Any]]:
        # Both checkout entry points take the session as their last argument.
        @contextmanager
        def checkout(self: Any, *args: Any) -> Iterator[Any]:
            if self is client:
                before()
            with original(self, *args) as connection:
                token = active.set((self is client, args[-1]))
                try:
                    yield connection
                finally:
                    active.reset(token)

        return checkout

    def refuse_unacknowledged() -> None:
        if active.get()[0]:
            raise ObligationContractDesignError("MongoDB histories require acknowledged writes (w >= 1)")

    def command(self: Any, dbname: str, spec: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        watched, session = active.get()
        if watched:
            before()
            concern = kwargs.get("write_concern")
            if spec.get("writeConcern", {}).get("w") == 0 or (concern is not None and not concern.acknowledged):
                refuse_unacknowledged()
        in_transaction = session is not None and session.in_transaction
        result = original_command(self, dbname, spec, *args, **kwargs)
        if watched and _writes(spec) and (not in_transaction or "commitTransaction" in spec):
            committed()
        return result

    def acknowledged_batch(send: Callable[[], Any]) -> Any:
        watched, session = active.get()
        if watched:
            before()
        in_transaction = session is not None and session.in_transaction
        result = send()
        if watched and not in_transaction:
            committed()
        return result

    def send_message(self: Any, *args: Any, **kwargs: Any) -> Any:
        if active.get()[0]:
            before()
        return original_send(self, *args, **kwargs)

    def bulk_write_command(original: Callable[..., Any]) -> Callable[..., Any]:
        # PyMongo 4.18+: one function sends acknowledged and unacknowledged batches.
        def run(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("unacknowledged"):
                refuse_unacknowledged()
                return original(*args, **kwargs)
            return acknowledged_batch(lambda: original(*args, **kwargs))

        return run

    def bulk_unack(self: Any, *args: Any, **kwargs: Any) -> Any:
        # Ordered w=0 bulks internally use acknowledged commands to stop on errors.
        # Reject the caller's original concern before that conversion sends a batch.
        refuse_unacknowledged()
        return original_bulk_unack(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(MongoClient, "_checkout", fenced(MongoClient._checkout))
        patch.setattr(Connection, "command", command)
        patch.setattr(Connection, "send_message", send_message)
        if pymongo.version_tuple >= (4, 18):
            # Reads no longer pass through _checkout; fence them where they check out.
            patch.setattr(MongoClient, "_conn_from_server", fenced(MongoClient._conn_from_server))
            for module in (bulk, client_bulk):
                patch.setattr(module, "run_bulk_write_command", bulk_write_command(module.run_bulk_write_command))
        else:
            original_write = Connection.write_command  # type: ignore[attr-defined]  # removed in 4.18
            original_unack = Connection.unack_write  # type: ignore[attr-defined]  # removed in 4.18

            def write_command(self: Any, *args: Any, **kwargs: Any) -> Any:
                return acknowledged_batch(lambda: original_write(self, *args, **kwargs))

            def unack_write(self: Any, *args: Any, **kwargs: Any) -> Any:
                refuse_unacknowledged()
                return original_unack(self, *args, **kwargs)

            patch.setattr(Connection, "write_command", write_command)
            patch.setattr(Connection, "unack_write", unack_write)
        patch.setattr(_Bulk, "execute_no_results", bulk_unack)
        yield


MongoDBWorker = CommitWorker


def mongodb_worker_killer(client: Any) -> Callable[[int | None], AbstractContextManager[MongoDBWorker]]:
    @contextmanager
    def killer(kill_after: int | None) -> Iterator[MongoDBWorker]:
        worker = MongoDBWorker(kill_after)
        with _watching(client, worker.refuse_if_dead, worker.committed):
            yield worker

    return killer


class MongoDBLostReplies(LostCommitReplies):
    """An acknowledged write loses its reply with the driver's connection error."""

    def __init__(self, lose_at: int | None) -> None:
        from pymongo.errors import ConnectionFailure

        super().__init__(
            lose_at, lambda count: ConnectionFailure(f"MongoDB reply to write {count} lost; the write landed")
        )


def mongodb_reply_breaker(client: Any) -> Callable[[int | None], AbstractContextManager[MongoDBLostReplies]]:
    @contextmanager
    def breaker(lose_at: int | None) -> Iterator[MongoDBLostReplies]:
        replies = MongoDBLostReplies(lose_at)
        with _watching(client, lambda: None, replies.committed):
            yield replies

    return breaker


def mongodb_host(client: Any, production_packages: Collection[str]) -> Host:
    """Configure write/reply faults and native find-cursor selection evidence."""
    from pytest_obligation.integrations.mongodb_selection import MongoDBSelectionInspector

    return Host(
        production_packages=frozenset(production_packages),
        selection_inspectors=(MongoDBSelectionInspector(client),),
        worker_killer=mongodb_worker_killer(client),
        reply_breaker=mongodb_reply_breaker(client),
    )
