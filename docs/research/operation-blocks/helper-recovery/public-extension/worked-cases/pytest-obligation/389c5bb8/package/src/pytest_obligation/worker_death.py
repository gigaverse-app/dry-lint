from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TypeVar


class WorkerDied(BaseException):
    """A worker died: nothing it would have done next happens. A BaseException, so ordinary error handling cannot swallow it."""


class CallbackFailed(Exception):  # noqa: N818 - named for what happened, like WorkerDied
    """
    An after-commit callback failed, as a real one does: a bug, a timeout, a provider error.

    An ordinary ``Exception``, unlike :class:`WorkerDied`: the process lives on,
    so what happens next is the framework's and the application's own error
    handling. Django, for one, skips every later non-robust callback of the same
    commit and re-raises; a ``robust=True`` callback's failure is logged instead.
    """


class ReceiverFailed(Exception):  # noqa: N818 - named for what happened, like WorkerDied
    """
    A signal receiver failed, as a real one does: a bug, or the backend it reports to unreachable.

    An ordinary ``Exception``: the process lives on. What happens next is the
    framework's own dispatch and the sender's error handling. Django's
    ``Signal.send`` propagates it to the sender and skips the receivers after
    it; ``send_robust`` logs it and carries on.
    """


def refuse_dead_worker(dead: bool, message: str) -> None:
    """Fence operations regardless of how a host records death."""
    if dead:
        raise WorkerDied(message)


class CommitWorker:
    """Count a client's durable writes and fence every later operation after death."""

    def __init__(self, kill_after: int | None, *, on_death: Callable[[], None] | None = None) -> None:
        self._on_death = on_death
        self._kill_after = kill_after
        self.commits = 0
        self.dead = False

    def committed(self) -> None:
        self.commits += 1
        if self.commits == self._kill_after:
            self.kill_now(f"worker died right after commit {self.commits}")

    def kill_now(self, reason: str) -> None:
        self.dead = True
        if self._on_death is not None:
            self._on_death()
        raise WorkerDied(reason)

    def refuse_if_dead(self) -> None:
        refuse_dead_worker(self.dead, "the worker is dead; its connection sends nothing more")


class LostCommitReplies:
    """Count acknowledged commits and lose one reply using the adapter's driver error."""

    def __init__(self, lose_at: int | None, failure: Callable[[int], Exception]) -> None:
        self._lose_at = lose_at
        self._failure = failure
        self.count = 0
        self.failure: Exception | None = None

    def committed(self) -> None:
        self.count += 1
        if self.count == self._lose_at:
            self.failure = self._failure(self.count)
            raise self.failure


_Replies = TypeVar("_Replies", bound=LostCommitReplies)


def counted_reply_breaker(
    watch: Callable[[Callable[[], None], Callable[[], None]], AbstractContextManager[object]],
    replies_factory: Callable[[int | None], _Replies],
) -> Callable[[int | None], AbstractContextManager[_Replies]]:
    """Keep the observer installed through the body, restoring it even when the reply is lost."""

    @contextmanager
    def breaker(lose_at: int | None) -> Iterator[_Replies]:
        replies = replies_factory(lose_at)
        with watch(lambda: None, replies.committed):
            yield replies

    return breaker
