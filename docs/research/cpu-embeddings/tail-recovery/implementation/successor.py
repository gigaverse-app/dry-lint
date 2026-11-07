"""Frozen V2: bounded append-only operation route, with exact original candidates first.

This isolates the source-supported abstention failure. It deliberately introduces
no speculative call binding: unresolved delegation is not a negative label.
Views, encoder, scores, floors and eligibility are identical to V1.
"""
from harness import Replay

COMPARER = 'cpu-complete-statements:2-append'

class SuccessorReplay(Replay):
    def __init__(self, folder):
        super().__init__(folder)
        self.op.version = '2-append'
        self.tail.comparer_id = COMPARER

    def proposals(self, query):
        arms = super().proposals(query)
        self.tail.discovery_keys = {candidate.key for candidate in arms['original']}
        additions = [self.tail.pair(query, target, score).model_copy(update={'lane': 'exploration'})
                     for target, score in self.tail.neighbours(query)]
        assert len(additions) <= 1
        arms['treatment'] = arms['original'] + additions
        return arms

    def ranks(self, query, target, arms):
        result = super().ranks(query, target, arms)
        stage = result['stages']['treatment']
        if not stage['retrieved'] and stage['first_loss'] == 'original_route_did_not_abstain':
            stage['first_loss'] = ('operation_score_floor' if result['operation']['score'] < .8
                                   else 'earlier_route_or_top1')
        result['recipe'] = COMPARER
        return result
