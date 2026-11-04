"""
The ledger: what dry-lint has cost and caught, across a pull request's pushes and a repository's merged pull requests.

- **A pull request's ledger travels in its sticky comment**, as one hidden `<!-- dry-lint-ledger {...} -->` line,
  the way CI-esta carries its snapshot. It needs no cache, so losing one loses nothing. Each run adds its figures
  once: runs are counted by id and attempt, so posting the same run again changes nothing.
- **A duplicate is kept out of the codebase** when a push reported it and a later push no longer does, without a
  person's decision (`distinct-from`, `ignore`, a pattern) settling it. A pair left unjudged is still open, and so
  is one whose scope (the local check, or the check against peer repositories) did not report on that push: a
  check that did not run cannot say the duplicate is gone. A pair from an older ledger, which never recorded its
  scope, stays open until a push reports it again (and so names its scope) or a person settles it.
- **An accepted baseline pair this pull request cleaned up** (`report.backlog`: a side removed, or judged `separate`
  now) is backlog, kept apart from the duplicates it kept out: that debt was already in the codebase. Each baseline
  check restates the whole list, so a pair that comes back drops out. The baseline and its badge move only with the
  repository's sweep.
- **A duplicate the pre-commit hook blocked** and saw fixed, or dismissed, before any push arrives in the commits'
  trailers (`dry-lint.commits`). It joins the pull request's pairs as settled before commit, unless a push has
  reported the pair itself: what CI saw wins.
- **A repository's ledger** is folded on the default branch: each push there adds its own run, and the final ledger
  of every pull request merged since, once. It lives beside the verdicts in the Actions cache, where every pull
  request can read it, and says since when it counts: losing the cache starts it again, never invents figures.
"""

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from dry_lint import __version__
from dry_lint.commits import Outcome
from dry_lint.evidence import PairEvidence
from dry_lint.models import SCHEMA, Versioned, pair_key
from dry_lint.report import BLUE, GRAY, Finding, Report, badge, code, plural

SNAPSHOT = re.compile(r"<!-- dry-lint-ledger (?P<ledger>\{.*?\}) -->")
RECENT_RUNS = 20
PUSHES_SHOWN = 30
EVIDENCE_BYTES = 16_000


def comment_json(model: BaseModel) -> str:
    return model.model_dump_json().replace("<", "\\u003c").replace(">", "\\u003e")


class Tally(BaseModel):
    """Additive figures for one run, or the sum of many."""

    runs: int = 0
    functions: int = Field(default=0, description="Changed functions checked, summed over runs.")
    codebase: int = Field(default=0, description="The most functions any run compared them with.")
    pairs: int = Field(default=0, description="Look-alike pairs compared.")
    judgments: int = Field(default=0, description="New verdicts: a judge was asked.")
    reused: int = Field(default=0, description="Verdicts reused from the store.")
    usd: float = 0.0
    unpriced: bool = Field(default=False, description="A judge's price was unknown, so `usd` is a lower bound.")
    subscription_calls: int = 0

    @classmethod
    def of(cls, report: Report) -> "Tally":
        stats, judging = report.stats, report.judging
        usd = judging.usd if judging else 0.0
        calls = sum(s.calls for s in judging.spend if s.subscription) if judging else 0
        return cls(runs=1, functions=report.changed, codebase=report.functions, pairs=stats["candidates"],
                   judgments=stats["judged"], reused=stats["cached"], usd=usd or 0.0, unpriced=usd is None,
                   subscription_calls=calls)

    def __add__(self, other: "Tally") -> "Tally":
        return Tally(runs=self.runs + other.runs, functions=self.functions + other.functions,
                     codebase=max(self.codebase, other.codebase), pairs=self.pairs + other.pairs,
                     judgments=self.judgments + other.judgments, reused=self.reused + other.reused,
                     usd=self.usd + other.usd, unpriced=self.unpriced or other.unpriced,
                     subscription_calls=self.subscription_calls + other.subscription_calls)

    def again(self) -> "Tally":
        """A re-run of a commit already counted: its judging costs again, but it checks nothing new."""
        return self.model_copy(update={"functions": 0, "pairs": 0})

    def cost(self) -> str:
        """What priced judging cost, with subscription calls; "unknown" when no judge had a price."""
        usd = f"${self.usd:.2f}" if self.usd >= 0.1 else f"${self.usd:.3f}" if self.usd >= 0.001 else (
            "under $0.001" if self.usd else "")
        calls = plural(self.subscription_calls, "subscription call") if self.subscription_calls else ""
        bill = " + ".join(part for part in (usd, calls) if part)
        return bill or ("unknown" if self.unpriced else "$0")

    def spent(self) -> str:
        """The cost as a phrase: "for $0.012 of judging", and whether an unpriced judge adds to it."""
        if self.cost() == "unknown":
            return "with an unpriced judge"
        return f"for {self.cost()} of judging" + (" plus an unpriced judge" if self.unpriced else "")


class Push(BaseModel):
    head: str
    tally: Tally
    reported: int = Field(default=0, description="Duplicates this push reported.")


class Pair(BaseModel):
    """A pair some push reported, and where it stands now."""

    new: str
    existing: str
    found: int = Field(description="The push that first reported it.")
    state: Literal["open", "kept-out", "dismissed"] = "open"
    settled: int | None = Field(default=None, description="The push that kept it out or dismissed it.")
    scope: str | None = Field(default=None, description="The report scope that found it; None in older ledgers.")
    lines: int = Field(default=0, description="Lines in the new function when last reported.")
    drifted: bool = Field(default=False, description="Last judged drifted: the two already behaved differently.")
    rewrite: bool = Field(default=False, description="Not a copy: the two functions' structure hashes differ.")
    before_commit: bool = Field(default=False, description="Settled by the pre-commit hook; from a commit's trailer.")
    evidence: PairEvidence | None = Field(default=None, description="Last reported source coordinates and verdict.")

    def concept(self) -> str:
        return code(self.new) if self.new == self.existing else f"{code(self.new)} ≈ {code(self.existing)}"


class Backlog(BaseModel):
    """An accepted baseline pair the pull request cleaned up, and how: remediation, never counted as kept out."""

    new: str
    existing: str
    how: Literal["removed", "separate"] = Field(description="A side removed, or judged separate as it is now.")
    settled: int = Field(description="The push that first cleaned it up.")


def local(qualname: str) -> str:
    """A function's name without its path: `Class.name`."""
    return qualname.split("::", 1)[1]


def describe(finding: Finding) -> tuple[int, bool, bool]:
    """A reported pair's size, whether it drifted, and whether it is a rewrite rather than a copy."""
    new, existing = finding.candidate.new, finding.candidate.existing
    drifted = finding.verdict is not None and finding.verdict.label == "drifted"
    return new.lines, drifted, bool(new.hash and existing.hash) and new.hash != existing.hash


class PullLedger(Versioned):
    """A pull request's ledger: every run's figures, every push, and every pair any push reported."""

    pushed: int = 0
    tally: Tally = Field(default_factory=Tally)
    pushes: list[Push] = Field(default_factory=list, description=f"The last {PUSHES_SHOWN} pushes.")
    pairs: dict[str, Pair] = Field(default_factory=dict)
    backlog: dict[str, Backlog] = Field(default_factory=dict, description="What the latest baseline check credits.")
    runs: list[str] = Field(default_factory=list, description=f"The last {RECENT_RUNS} runs counted.")

    def count(self, state: str) -> int:
        """The pairs in `state`, apart from the backlog: a cleaned-up accepted pair was never kept out."""
        return sum(pair.state == state and key not in self.backlog for key, pair in self.pairs.items())

    def kept_out(self) -> list[Pair]:
        """The duplicates kept out whose details were recorded: a pair an older version reported has none."""
        return [pair for key, pair in self.pairs.items()
                if pair.state == "kept-out" and pair.lines and key not in self.backlog]

    def advance(self, reports: list[Report], run: str = "", scopes: list[str] = (),
                before_commit: list[Outcome] = ()) -> "PullLedger":
        """
        This ledger with one more run added; the same ledger if that run was counted already. `scopes` names each
        report's scope ("" when not given); only the scopes that reported can settle the pairs they found.
        `before_commit` is what the pull request's commit trailers say the pre-commit hook settled.
        """
        if not reports or (run and run in self.runs):
            return self
        named = [*scopes, *[""] * (len(reports) - len(scopes))]
        completed = set(named)
        ledger = self.model_copy(deep=True, update={"schema_version": SCHEMA})
        tally = sum((Tally.of(report) for report in reports), Tally())
        findings = [f for report in reports for f in report.findings]
        reported = {f.candidate.key: (f, scope) for report, scope in zip(reports, named) for f in report.findings
                    if f.reported}
        evidence = {f.candidate.key: PairEvidence.of(f, report.run) for report in reports for f in report.findings
                    if f.reported}
        head = reports[0].run.head
        if ledger.pushes and ledger.pushes[-1].head == head:
            tally = tally.again()
            last = ledger.pushes[-1]
            last.tally, last.reported = last.tally + tally, len(reported)
        else:
            ledger.pushed += 1
            ledger.pushes = [*ledger.pushes, Push(head=head, tally=tally, reported=len(reported))][-PUSHES_SHOWN:]
        ledger.tally = ledger.tally + tally
        ledger.runs = [*ledger.runs, run][-RECENT_RUNS:] if run else ledger.runs
        unjudged = {f.candidate.key for f in findings if f.deferred or f.verdict is None}
        settled_by_rule = {c.key for report in reports for c in report.filtered}
        for key, (finding, scope) in reported.items():
            names = [local(side.qualname) for side in (finding.candidate.new, finding.candidate.existing)]
            pair = ledger.pairs.setdefault(key, Pair(new=names[0], existing=names[1], found=ledger.pushed))
            pair.state, pair.settled, pair.scope, pair.before_commit = "open", None, scope, False  # what CI saw wins
            pair.lines, pair.drifted, pair.rewrite = describe(finding)
            pair.evidence = evidence[key]
        for outcome in before_commit:
            if outcome.key not in ledger.pairs:
                ledger.pairs[outcome.key] = Pair(new=outcome.new, existing=outcome.existing, found=ledger.pushed,
                                                 state=outcome.state, settled=ledger.pushed, lines=outcome.lines,
                                                 before_commit=True)
        for key, pair in ledger.pairs.items():
            if key in reported or key in unjudged:
                continue
            if key in settled_by_rule and pair.state != "dismissed":  # a person's decision, even after the fact
                pair.state, pair.settled = "dismissed", ledger.pushed
            elif pair.state == "open" and pair.scope in completed:  # absent only from a check that ran
                pair.state, pair.settled = "kept-out", ledger.pushed
        if any(report.backlog is not None for report in reports):  # each baseline check restates the whole backlog
            cleaned = {pair_key(item.new, item.existing): item for report in reports for item in report.backlog or ()}
            ledger.backlog = {
                key: ledger.backlog[key].model_copy(update={"how": item.how}) if key in ledger.backlog
                else Backlog(new=local(item.new), existing=local(item.existing), how=item.how, settled=ledger.pushed)
                for key, item in cleaned.items()}
        remaining = EVIDENCE_BYTES
        for pair in reversed(ledger.pairs.values()):
            if pair.evidence:
                size = len(comment_json(pair.evidence).encode())
                if size > remaining:
                    pair.evidence = None
                else:
                    remaining -= size
        return ledger

    def contribution(self, key: str, number: int) -> dict:
        """What the global counter is sent for this pull request once merged: counts, and the repository's key."""
        return {"repository": key, "pull": number,
                "kept_out": self.count("kept-out"), "caught": len(self.pairs), "dismissed": self.count("dismissed"),
                "merged_open": self.count("open"), "pushes": self.pushed, "runs": self.tally.runs,
                "judgments": self.tally.judgments, "functions": self.tally.functions, "pairs": self.tally.pairs,
                "reused": self.tally.reused, "usd": round(self.tally.usd, 6), "measured_kept_out": len(self.kept_out()),
                "drifted_kept_out": sum(pair.drifted for pair in self.kept_out()),
                "rewrites_kept_out": sum(pair.rewrite for pair in self.kept_out()),
                "lines_kept_out": sum(pair.lines for pair in self.kept_out()), "version": __version__}

    def snapshot(self) -> str:
        return f"<!-- dry-lint-ledger {comment_json(self)} -->"

    @classmethod
    def read(cls, body: str) -> "PullLedger | None":
        match = SNAPSHOT.search(body)
        if not match:
            return None
        try:
            return cls.model_validate_json(match.group("ledger"))
        except ValidationError:
            return None


def headline(ledger: PullLedger) -> str:
    """The sentence a reader remembers: what this pull request's checks cost, and what they caught."""
    tally, kept, still = ledger.tally, ledger.count("kept-out"), ledger.count("open")
    across = f"across {ledger.pushed:,} pushes" if ledger.pushed > 1 else "on its first push"
    backlog = f"**{plural(len(ledger.backlog), 'accepted backlog pair')} cleaned up.** " if ledger.backlog else ""
    if kept:
        tail = f" {plural(still, 'duplicate')} still open." if still else ""
        hooked = sum(pair.before_commit for pair in ledger.kept_out())
        early = f" ({hooked:,} by the pre-commit hook, before commit)" if hooked else ""
        return f"{backlog}**{plural(kept, 'duplicate')} kept out of the codebase**{early} {tally.spent()}, {across}.{tail}"
    if still:
        return (f"{backlog}**{plural(still, 'duplicate')} caught** {tally.spent()}, {across}. "
                "Each one fixed here is kept out of the codebase.")
    if not tally.functions:
        return f"{backlog}**No changed functions to check yet**, {across}."
    return f"{backlog}**{plural(tally.functions, 'function')} checked, nothing duplicated**, {tally.spent()}, {across}."


ICONS = {"kept-out": "✅", "open": "🟡", "dismissed": "⚪"}
# GitHub sizes a comment's tables to their content. A wide spacer floated into each cell, which GitHub then caps at
# the comment's width, stretches a table across the comment on any screen while adding only one pixel of height.
# It floats right: GitHub pads a floated image by 20px on the side away from its float, and padding past the left
# edge never scrolls, where past the right edge it gives the table a scrollbar.
SPREAD = '<img width="2000" height="1" align="right" alt="">'


def pair_line(pair: Pair) -> str:
    if pair.before_commit:
        done = "kept out" if pair.state == "kept-out" else "dismissed by a person's decision"
        return f"{ICONS[pair.state]} {pair.concept()} · {done} before commit, by the pre-commit hook"
    where = {"kept-out": f"kept out in push {pair.settled}", "open": "still open",
             "dismissed": f"dismissed by a person's decision in push {pair.settled}"}[pair.state]
    return f"{ICONS[pair.state]} {pair.concept()} · found in push {pair.found}, {where}"


def backlog_line(key: str, item: Backlog, ledger: PullLedger) -> str:
    how = "one side removed" if item.how == "removed" else "the judge now finds them separate"
    found = f"found in push {ledger.pairs[key].found}, " if key in ledger.pairs else ""
    concept = Pair(new=item.new, existing=item.existing, found=item.settled).concept()
    return f"{ICONS['kept-out']} {concept} · accepted backlog, {found}cleaned up in push {item.settled}: {how}"


def render(ledger: PullLedger, repository: "RepositoryLedger | None" = None, comparisons: str = "") -> str:
    """Cleanup progress first, with the current outcomes and the commits that cleared them."""
    tally, kept, still, backlog = ledger.tally, ledger.count("kept-out"), ledger.count("open"), len(ledger.backlog)
    cleaned = Counter([*(pair.settled for key, pair in ledger.pairs.items()
                         if pair.state == "kept-out" and key not in ledger.backlog),
                       *(item.settled for item in ledger.backlog.values())])
    split = " · ".join(part for part in (f"{backlog:,} from the accepted backlog" if backlog else "",
                                         f"{kept:,} found here" if kept and backlog else "") if part)
    badges = [badge("pushes", ledger.pushed, GRAY), badge("functions checked", f"{tally.functions:,}", GRAY),
              badge("judgments", f"{tally.judgments:,}", GRAY), badge("spent", tally.cost(), BLUE)]
    title = "### 🧹 A little less lint" if kept or backlog else "### 🧺 This PR's cleanup basket"
    cells = [f"{SPREAD}**{plural(n, 'pair')}**" for n in (kept + backlog, still, ledger.count("dismissed"))]
    cells[0] += f"<br><sub>{split}</sub>" if split else ""
    lines = [title, "", "| 🧼 Cleaned up | 🧶 Still tangled | 🏷️ Dismissed |", "| :--: | :--: | :--: |",
             "| " + " | ".join(cells) + " |", ""]
    if cleaned[ledger.pushed] and ledger.pushes:
        lines += [f"Latest analyzed commit `{ledger.pushes[-1].head[:7]}` · "
                  f"**+{plural(cleaned[ledger.pushed], 'pair')} cleaned up** ✨", ""]
    if comparisons:
        lines += [comparisons, ""]
    lines += ["<details><summary><strong>History and check stats</strong></summary>", "",
              headline(ledger), "", " ".join(badges), "",
              "<sub>Previously reported pairs no longer reported, here or by the pre-commit hook before commit; "
              "dismissals do not count as cleanup. Counts reflect current outcomes across analyzed commits."
              + (" Accepted backlog pairs count when this pull request removes a side or the judge now finds them "
                 "separate; the baseline and its badge change only with the repository's audit." if backlog else "")
              + "</sub>", ""]
    if ledger.pushed > 1 or ledger.pairs or ledger.backlog:
        first = ledger.pushed - len(ledger.pushes) + 1
        rows = ["| Push | Commit | Changed | Look-alikes | Judged | Duplicates | Cleaned here | Cost |",
                "| --: | :-- | --: | --: | --: | --: | --: | --: |"]
        for n, push in enumerate(ledger.pushes, first):
            reused = f" <sub>+{push.tally.reused:,} reused</sub>" if push.tally.reused else ""
            cleared = f"**+{cleaned[n]}**" if cleaned[n] else "0"
            rows.append(f"| {n} | `{push.head[:7]}` | {push.tally.functions:,} | {push.tally.pairs:,} | "
                        f"{push.tally.judgments:,}{reused} | {push.reported:,} | {cleared} | {push.tally.cost()} |")
        rows.append(f"| **{ledger.pushed}** | | **{tally.functions:,}** | **{tally.pairs:,}** | "
                    f"**{tally.judgments:,}** | | **{kept + backlog:,}** | **{tally.cost()}** |")
        pairs = sorted((pair for key, pair in ledger.pairs.items() if key not in ledger.backlog),
                       key=lambda p: (list(ICONS).index(p.state), p.found))
        backlogged = sorted(ledger.backlog.items(), key=lambda entry: entry[1].settled)
        items = [*(backlog_line(key, item, ledger) for key, item in backlogged), *(pair_line(pair) for pair in pairs)]
        lines += [*rows, "", *(f"- {item}" for item in items), *([""] if items else [])]
    if repository and repository.pulls:
        lines += [f"<sub>{repository.line()}</sub>", ""]
    lines += ["</details>", ""]
    return "\n".join([*lines, ledger.snapshot()])


def counter_key(repository_id: str) -> str:
    """
    The global counter's name for a repository: the SHA-256 of its numeric GitHub id, never of its name. It is
    pseudonymous, not anonymous: it ties one repository's pull requests together. But a name alone does not lead
    to it, since a private repository's id is visible only to people who can see the repository, and the key
    survives renames and transfers.
    """
    return hashlib.sha256(f"github-repository:{repository_id.strip()}".encode()).hexdigest()


class RepositoryLedger(Versioned):
    """A repository's ledger: its default-branch runs and the final ledgers of its merged pull requests."""

    repository: str = ""
    since: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    pulls: list[int] = Field(default_factory=list, description="Merged pull requests already counted.")
    unaccounted: list[int] = Field(default_factory=list, description="Merged pull requests that had no ledger.")
    runs: list[str] = Field(default_factory=list, description=f"The last {RECENT_RUNS} default-branch runs counted.")
    tally: Tally = Field(default_factory=Tally)
    pushes: int = 0
    kept_out: int = 0
    dismissed: int = 0
    merged_open: int = Field(default=0, description="Duplicates still open when their pull request merged.")
    outbox: list[dict] = Field(default_factory=list, description="Contributions the global counter has not confirmed.")

    def add_run(self, tally: Tally, run: str) -> None:
        if run and run in self.runs:
            return
        self.tally = self.tally + tally
        self.runs = [*self.runs, run][-RECENT_RUNS:] if run else self.runs

    def add_pull(self, number: int, ledger: PullLedger, key: str = "") -> None:
        """Count a merged pull request once; with the repository's counter `key`, queue its counts for the counter."""
        if number in self.pulls:
            return
        self.pulls.append(number)
        if key:
            self.outbox.append(ledger.contribution(key, number))
        self.tally = self.tally + ledger.tally
        self.pushes += ledger.pushed
        self.kept_out += ledger.count("kept-out")
        self.dismissed += ledger.count("dismissed")
        self.merged_open += ledger.count("open")

    def line(self) -> str:
        since, name = datetime.fromisoformat(self.since), code(self.repository) if self.repository else "This repository"
        return (f"🏆 {name} since {since:%b} {since.day}, {since.year}: "
                f"**{plural(self.kept_out, 'duplicate')} kept out of the codebase** across "
                f"{plural(len(self.pulls), 'merged pull request')}, {self.tally.spent()}.")

    @classmethod
    def load(cls, text: str, repository: str) -> "RepositoryLedger":
        """The saved ledger, or a new one from today when there is none or it cannot be read."""
        try:
            return cls.model_validate(json.loads(text))
        except (ValueError, ValidationError):
            return cls(repository=repository)
