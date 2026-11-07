"""Bounded checks against the actual fixed diagnostic population and PR109 routes."""
from common import *
from harness import Replay
from successor import SuccessorReplay, COMPARER
from dry_lint.models import Candidate

def test_append_after_original_is_exact_top_one_and_keeps_original_funding():
    folder = next(p.parent for p in folders() if p.parent.name.startswith('62d814'))
    rows = read(HERE/'cohorts'/folder.name/'diagnosis.jsonl')
    row = next(r for r in rows if r['original_nonabstention'] and r['counterfactual_funded'])
    replay = SuccessorReplay(folder)
    query = replay.fs[row['query_position']]
    arms = replay.proposals(query)
    expected = Candidate.model_validate(row['candidate']).model_copy(update={'comparer': COMPARER})
    assert [c.model_dump(mode='json') for c in arms['treatment']] == [c.model_dump(mode='json') for c in arms['original'] + [expected]]
    assert [c.model_dump(mode='json') for c in arms['original']] == row['original_candidates']
    assert expected.new.code == query.code
    assert expected.existing.code == replay.fs[row['target_position']].code
    for paired in (True, False):
        before = replay.ledger(arms['original'], paired)
        after = replay.ledger(arms['treatment'], paired)
        assert after[:len(before)] == before
    assert replay.ranks(query, expected.existing, arms)['stages']['treatment']['first_loss'] == 'retained'

def test_existing_v1_winner_keeps_full_source_and_score():
    folder = next(p.parent for p in folders() if p.parent.name.startswith('62d814'))
    row = read(HERE/'cohorts'/folder.name/'discovery-candidates.jsonl')[0]
    replay = SuccessorReplay(folder)
    arms = replay.proposals(replay.fs[row['query_position']])
    expected = Candidate.model_validate(row['candidate']).model_copy(update={'comparer': COMPARER})
    assert arms['treatment'][-1].model_dump(mode='json') == expected.model_dump(mode='json')
    assert len(arms['treatment']) == len(arms['original']) + 1
