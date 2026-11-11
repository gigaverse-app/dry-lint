// The discovery campaign ledger (src/dry_lint/discovery.py: CampaignStore), at its public API.
// Money is in eighths of a dollar so every amount is exact in both Quint and Python floats.
// Settings: budget $1 (8), baseline_fraction 0.5 so the exploration cap is $0.50 (4), $0.25 (2) of
// exploration credit per revision, at most 3 calls per revision, 2 exploration calls per revision,
// and 5 calls in the whole campaign, of which int(5 * 0.5) = 2 may be protected exploration.
module campaign {
  pure val BUDGET = 8
  pure val CAP = 4
  pure val PER_REVISION = 2
  pure val CALLS_PER_REVISION = 3
  pure val EXPLORATION_CALLS_PER_REVISION = 2
  pure val CALLS = 5
  pure val PROTECTED_EXPLORATION_CALLS = 2

  // kind: "baseline" | "exploration" (protected) | "residual" (recovery after the protected pass) | "family"
  type Attempt = { rev: int, kind: str, cand: str, cost: int, status: str }
  type Outcome = NoOutcome | Reserved(int) | OverBudget | Refused | NotEntered | Settled(int) | AlreadySettled
  type Event = { op: str, kind: str, cand: str, cost: int, idx: int, actual: int, success: bool }
  type View = { rev: int, revisions: int, credit: int, attempts: List[Attempt], outcome: Outcome }

  var event: Event
  var observed: View
  // Model-only: which revisions have been entered (the API shows only their count).
  var entered: Set[int]

  pure val NONE = { op: "", kind: "", cand: "", cost: 0, idx: 0, actual: 0, success: false }

  pure def spent(attempts: List[Attempt]): int = attempts.foldl(0, (total, a) => total + a.cost)
  pure def onRev(attempts: List[Attempt], rev: int): List[Attempt] = attempts.select(a => a.rev == rev)
  pure def allAnswered(attempts: List[Attempt]): bool = attempts.foldl(true, (ok, a) => ok and a.status == "answered")
  pure def explorationLike(a: Attempt): bool = a.kind != "baseline"
  pure def min(a: int, b: int): int = if (a < b) a else b

  // CampaignStore._enter: a revision mints its credit once, never above the cap.
  pure def enterCredit(credit: int, isNew: bool): int = if (isNew) min(CAP, credit + PER_REVISION) else credit

  pure def callRoom(attempts: List[Attempt], current: List[Attempt], exploring: bool): bool = and {
    current.length() < CALLS_PER_REVISION,
    attempts.length() < CALLS,
    not(exploring) or current.select(explorationLike).length() < EXPLORATION_CALLS_PER_REVISION,
  }

  action init = all {
    event' = { ...NONE, op: "init" },
    observed' = { rev: 0, revisions: 0, credit: 0, attempts: [], outcome: NoOutcome },
    entered' = Set(),
  }

  // A new push: later calls use the next immutable revision.
  action push = all {
    observed.rev < 1,
    event' = { ...NONE, op: "push" },
    observed' = { ...observed, rev: observed.rev + 1, outcome: NoOutcome },
    entered' = entered,
  }

  action advance = {
    val isNew = not(entered.contains(observed.rev))
    all {
      event' = { ...NONE, op: "advance" },
      observed' = {
        ...observed,
        revisions: if (isNew) observed.revisions + 1 else observed.revisions,
        credit: enterCredit(observed.credit, isNew),
        outcome: NoOutcome,
      },
      entered' = entered.union(Set(observed.rev)),
    }
  }

  // CampaignStore.reserve for a pair: baseline, protected exploration, or residual recovery.
  pure def admit(view: View, isNew: bool, kind: str, cand: str, cost: int): { view: View, outcome: Outcome } = {
    val credit = enterCredit(view.credit, isNew)
    val revisions = if (isNew) view.revisions + 1 else view.revisions
    val all_ = view.attempts
    val current = onRev(all_, view.rev)
    val exploring = kind != "baseline"
    val explored = all_.select(explorationLike)
    val room = BUDGET - spent(all_)
    val protectedRoom = min(min(room, CAP - spent(explored)), credit)
    val entered_ = { ...view, revisions: revisions, credit: credit }
    if (kind == "residual" and not(allAnswered(current))) { view: entered_, outcome: Refused }
    else if (current.select(a => a.cand == cand).length() > 0) { view: entered_, outcome: Refused }
    else if (not(callRoom(all_, current, exploring))) { view: entered_, outcome: Refused }
    else if (kind == "exploration" and explored.length() >= PROTECTED_EXPLORATION_CALLS) { view: entered_, outcome: Refused }
    else if (cost > (if (kind == "exploration") protectedRoom else room)) { view: entered_, outcome: OverBudget }
    else {
      view: {
        ...entered_,
        attempts: all_.append({ rev: view.rev, kind: kind, cand: cand, cost: cost, status: "reserved" }),
        credit: if (kind == "exploration") credit - cost else credit,
      },
      outcome: Reserved(all_.length()),
    }
  }

  action reserve(kind: str, cand: str, cost: int): bool = {
    val result = admit(observed, not(entered.contains(observed.rev)), kind, cand, cost)
    all {
      event' = { ...NONE, op: "reserve", kind: kind, cand: cand, cost: cost },
      observed' = { ...result.view, outcome: result.outcome },
      entered' = entered.union(Set(observed.rev)),
    }
  }

  // CampaignStore.reserve_family: one residual question for a whole family, after the protected pass.
  action reserveFamily(cost: int): bool = {
    val current = onRev(observed.attempts, observed.rev)
    val outcome =
      if (not(entered.contains(observed.rev))) NotEntered
      else if (not(allAnswered(current))) Refused
      else if (current.select(a => a.cand == "family").length() > 0) Refused
      else if (not(callRoom(observed.attempts, current, true))) Refused
      else if (cost > BUDGET - spent(observed.attempts)) OverBudget
      else Reserved(observed.attempts.length())
    all {
      event' = { ...NONE, op: "reserveFamily", kind: "family", cand: "family", cost: cost },
      observed' = {
        ...observed,
        attempts: match outcome {
          | Reserved(_) => observed.attempts.append(
              { rev: observed.rev, kind: "family", cand: "family", cost: cost, status: "reserved" }
            )
          | _ => observed.attempts
        },
        outcome: outcome,
      },
      entered' = entered,
    }
  }

  // CampaignStore.settle: a reservation settles exactly once. Known usage replaces the reservation (and
  // refunds protected exploration credit); unknown usage (actual = -1) keeps the reservation charged.
  action settle(idx: int, actual: int, success: bool): bool = {
    val a = observed.attempts[idx]
    val charged = if (actual < 0) a.cost else actual
    val refund = if (a.kind == "exploration") a.cost - charged else 0
    all {
      event' = { ...NONE, op: "settle", idx: idx, actual: actual, success: success },
      observed' = if (a.status != "reserved") { ...observed, outcome: AlreadySettled }
        else {
          ...observed,
          attempts: observed.attempts.replaceAt(
            idx, { ...a, cost: charged, status: if (success) "answered" else "failed" }
          ),
          credit: observed.credit + refund,
          outcome: Settled(charged),
        },
      entered' = entered,
    }
  }

  action inspect = all { event' = { ...NONE, op: "inspect" }, observed' = observed, entered' = entered }

  action step = any {
    push,
    advance,
    {
      nondet kind = Set("baseline", "exploration", "residual").oneOf()
      nondet cand = Set("c1", "c2").oneOf()
      nondet cost = 1.to(3).oneOf()
      reserve(kind, cand, cost)
    },
    {
      nondet cost = 1.to(3).oneOf()
      reserveFamily(cost)
    },
    all {
      observed.attempts.length() > 0,
      nondet idx = observed.attempts.indices().oneOf()
      nondet choice = Set(-1, 0, 1, 2, 3).oneOf()
      // A provider bills at most the conservative reservation.
      val actual = if (choice > observed.attempts[idx].cost) observed.attempts[idx].cost else choice
      nondet success = Set(true, false).oneOf()
      settle(idx, actual, success)
    },
  }

  // Admission never lets spending pass the budget while providers bill within their reservations,
  // and credit stays between zero and the exploration cap.
  val withinBudget = and {
    spent(observed.attempts) <= BUDGET,
    0 <= observed.credit and observed.credit <= CAP,
    observed.attempts.length() <= CALLS,
  }

  run creditMintedOncePerRevisionTest =
    init.then(advance).then(advance).then(push).then(advance)
      .then(all { assert(observed.revisions == 2 and observed.credit == CAP), inspect })

  run secondSettleIsRefusedTest =
    init.then(advance).then(reserve("exploration", "c1", 2)).then(settle(0, 1, true)).then(settle(0, 0, false))
      .then(all { assert(observed.outcome == AlreadySettled and observed.credit == 1), inspect })

  run residualWaitsForTheProtectedPassTest =
    init.then(reserve("baseline", "c1", 1)).then(reserve("residual", "c2", 1))
      .then(all { assert(observed.outcome == Refused), inspect })
      .then(settle(0, -1, true)).then(reserve("residual", "c2", 1))
      .then(all { assert(observed.outcome == Reserved(1)), inspect })

  run familyNeedsAnEnteredRevisionTest =
    init.then(reserveFamily(1)).then(all { assert(observed.outcome == NotEntered), inspect })
      .then(advance).then(reserveFamily(1)).then(all { assert(observed.outcome == Reserved(0)), inspect })
}
