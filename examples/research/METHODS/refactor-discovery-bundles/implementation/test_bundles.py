# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E741, F403, F405, I001
"""Offline invariant and native-integration tests; unittest avoids repository test fixtures."""

import copy
import unittest
from bundles import *
from run_study import load_cohort, CID
from consolidation_controls import control
from quest_demo import InspectionQuest
from dry_lint.models import Verdict

HERE = Path(__file__).resolve().parent


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.fs, cls.detector = load_cohort(CID)
        cls.raw = json.loads((HERE / "samples/due-183-manual1-before-bank-two-hop-proxy.json").read_text())

    def sample(self):
        return Bundle.model_validate(copy.deepcopy(self.raw))

    def test_end_to_end_source_schema_report_renderer(self):
        b = self.sample()
        self.assertEqual(b, Bundle.model_validate_json(b.model_dump_json(by_alias=True)))
        validate_source(b, self.fs, self.source)
        report = native_report(b)
        self.assertEqual(len(report.findings), len(b.leads) + 1)
        self.assertTrue(
            all(not f.reported and not f.related and not f.blocking and f.verdict is None for f in report.findings)
        )
        rendered = render(b)
        for f in unique_functions(b).values():
            self.assertIn(f.code, rendered)
            self.assertIn(source_url(b.seed.source, f), rendered)
        self.assertIn("not duplicate findings", rendered)

    def test_unjudged_flags_cannot_be_promoted(self):
        for flag in ("reported", "related", "blocking"):
            raw = copy.deepcopy(self.raw)
            raw["leads"][0][flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                Bundle.model_validate(raw)

    def test_no_verdict_field_on_lead(self):
        raw = copy.deepcopy(self.raw)
        raw["leads"][0]["verdict"] = {"label": "duplicate"}
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_body_digest_preserved(self):
        raw = copy.deepcopy(self.raw)
        raw["leads"][0]["candidate"]["existing"]["code"] += "\n# altered"
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_consistent_forged_body_rejected_by_source_inventory(self):
        b = self.sample()
        l = b.leads[0]
        l.candidate.existing.code += "\n# forged"
        l.boundaries = [Boundary.of(f) for f in (l.candidate.new, l.candidate.existing)]
        with self.assertRaises(ValueError):
            validate_source(b, self.fs, self.source)

    def test_global_revision_change_rejected_against_manifest(self):
        raw = copy.deepcopy(self.raw)
        raw["seed"]["source"]["revision"] = "0" * 40
        for l in raw["leads"]:
            l["source"]["revision"] = "0" * 40
        b = Bundle.model_validate(raw)
        with self.assertRaises(ValueError):
            validate_source(b, self.fs, self.source)

    def test_scope_mismatch_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["leads"][0]["source"]["scope"]["include"] = ["changed/*"]
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_transitive_path_does_not_prove_anchor_pair(self):
        raw = copy.deepcopy(self.raw)
        l = raw["leads"][0]
        l["path"] = [l["path"][0], "invented::intermediate", l["path"][-1]]
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_orphan_path_rejected(self):
        raw = copy.deepcopy(self.raw)
        l = raw["leads"][0]
        l["path"][0] = "orphan::f"
        l["edges"][0]["left"] = "orphan::f"
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_anchor_is_retained_and_duplicates_removed(self):
        b = self.sample()
        self.assertEqual(native_report(b).findings[0].candidate, b.seed.candidate)
        raw = copy.deepcopy(self.raw)
        raw["leads"] = raw["leads"][:1] * 2
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_source_budget_is_enforced(self):
        raw = copy.deepcopy(self.raw)
        raw["max_source_token_proxy"] = 1
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_false_or_disputed_seed_cannot_expand(self):
        for status in ("rejected", "disputed"):
            raw = copy.deepcopy(self.raw)
            raw["seed"]["status"] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                Bundle.model_validate(raw)
            self.assertEqual(branch_feedback(status, self.sample().leads, set()), [])

    def test_real_prior_seed_requires_actual_finding(self):
        raw = copy.deepcopy(self.raw)
        raw["seed"]["mode"] = "real_prior_judge_confirmed"
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_reserved_sources_rejected(self):
        raw = self.source.model_dump()
        raw["repository"] = "anomalyco/opencode"
        with self.assertRaises(ValueError):
            Source.model_validate(raw)

    def test_source_review_required_and_categories_preserved(self):
        for state in ("source-reviewed", "rejected", "disputed", "already-shared"):
            raw = copy.deepcopy(self.raw)
            raw["leads"][0]["state"] = state
            with self.subTest(state=state), self.assertRaises(ValueError):
                Bundle.model_validate(raw)

    def test_native_relatives_honor_parent_lane_and_changed_existing(self):
        c = self.sample().seed.candidate
        # Function.tokens are intentionally excluded from native serialized records.
        # Rebind exact inventory objects before exercising the real retrieval implementation.
        c = c.model_copy(
            update={"new": self.detector.find(c.new.qualname), "existing": self.detector.find(c.existing.qualname)}
        )
        actual = self.detector.relatives([c.new], [c])
        self.assertGreater(len(actual), 0)
        self.assertTrue(all(x.parent == c.key and x.lane == "relative" for x in actual))
        self.assertEqual(self.detector.relatives([c.new], [c.model_copy(update={"lane": "exploration"})]), [])
        self.assertEqual(self.detector.relatives([c.new, c.existing], [c]), [])
        self.assertEqual(
            self.detector.relatives([c.new], [c.model_copy(update={"filtered": "forwarding wrapper"})]), []
        )

    def test_branch_local_rejection_preserves_unrelated_leads(self):
        leads = self.sample().leads
        rejected = {leads[0].candidate.key}
        expected = [l for l in leads if l.path[:2] != leads[0].path[:2] and l.candidate.key not in rejected]
        self.assertGreater(len(expected), 0)
        self.assertEqual(branch_feedback("supported", leads, rejected), expected)
        self.assertEqual(branch_feedback("supported", leads, rejected, "cluster-wide"), [])

    def test_cluster_wide_comparison_stop(self):
        self.assertEqual(feedback_state("supported", ["rejected"]), "paused-boundary-review")
        self.assertEqual(feedback_state("supported", ["rejected", "already-shared"]), "stopped-rejections")

    def test_negative_after_pin_cannot_reuse_before_evidence(self):
        after = Bundle.model_validate_json((HERE / "samples/after-consolidation-control.json").read_text())
        self.assertEqual(after.leads, [])
        self.assertEqual(after.seed.review.category, "separate")
        self.assertNotEqual(after.seed.source.revision, self.source.revision)
        with self.assertRaises(ValueError):
            validate_source(after, self.fs, self.source)

    def test_shared_context_has_real_accounted_cost(self):
        m = metrics(self.sample())
        self.assertGreater(m["extra_source_token_proxy_over_anchor"], 0)
        self.assertGreater(m["source_token_reuse"], 0)
        self.assertGreater(m["rendered_report_token_proxy"], m["bundle_source_token_proxy"])
        self.assertIsNone(m["actual_agent_minutes"])

    def test_actual_forwarding_rule_prevents_after_wrapper_lead(self):
        result = control()
        self.assertIsNone(result["results"]["before"]["filtered"])
        self.assertEqual(result["results"]["after"]["filtered"], "forwarding wrapper")
        raw = copy.deepcopy(self.raw)
        raw["leads"][0]["candidate"]["filtered"] = "forwarding wrapper"
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)
        # Synthetic transport exercise: settled evidence can be retained separately.
        raw["leads"][0]["state"] = "already-shared"
        raw["leads"][0]["review"] = raw["seed"]["review"] | {
            "category": "already-shared",
            "evidence": "Synthetic transport fixture only, not a new source assessment",
            "inspected": raw["leads"][0]["boundaries"],
        }
        retained = Bundle.model_validate(raw)
        self.assertEqual(retained.leads[0].state, "already-shared")
        self.assertTrue(all(not f.reported and not f.blocking for f in native_report(retained).findings))

    def test_graph_handoff_remains_unjudged(self):
        raw = json.loads((HERE / "samples/graph-graph-bounded_seed_diffusion.json").read_text())
        b = Bundle.model_validate(raw)
        self.assertGreater(len(b.leads), 0)
        report = native_report(b)
        self.assertTrue(
            all(f.verdict is None and not f.reported and not f.related and not f.blocking for f in report.findings)
        )
        raw["leads"][0]["direct_pair_evidence"] = ""
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)

    def test_disputed_quest_does_not_become_new_gold(self):
        q = InspectionQuest.model_validate_json((HERE / "samples/prior-exposed-quest.json").read_text())
        self.assertFalse(q.confirmed_seed)
        self.assertFalse(q.automatic_expansion)
        self.assertEqual([i.state for i in q.items], ["disputed", "supported-unjudged"])
        self.assertTrue(all(not i.reported and not i.blocking and not i.related for i in q.items))
        self.assertEqual(q.items[0].review.category, "disputed")

    def test_confirmed_anchor_is_not_overwritten_by_unknown_leads(self):
        # Synthetic in-memory transport check only; not an observed provider confirmation.
        b = self.sample()
        f = Finding(
            candidate=b.seed.candidate,
            verdict=Verdict(label="duplicate", score=1.0, judge="synthetic-test-only"),
            reported=True,
            blocking=True,
        )
        raw = b.model_dump(by_alias=True)
        raw["seed"]["mode"] = "real_prior_judge_confirmed"
        raw["seed"]["prior_finding"] = f.model_dump()
        projected = native_report(Bundle.model_validate(raw))
        self.assertEqual(projected.findings[0], f)
        self.assertTrue(all(not x.reported and not x.related and not x.blocking for x in projected.findings[1:]))

    def test_high_calibration_estimate_never_creates_truth(self):
        raw = copy.deepcopy(self.raw)
        raw["leads"][0]["calibration"] = {
            "estimate": 0.999,
            "method": "synthetic transport test",
            "artifact": "test-only",
            "artifact_sha256": "0" * 64,
            "split_contract_sha256": "1" * 64,
            "population": "selected labeled pairs only",
            "target_definition": "registry positive",
            "held_out_prediction": True,
        }
        b = Bundle.model_validate(raw)
        self.assertEqual(b.leads[0].state, "supported-unjudged")
        self.assertTrue(all(not f.reported for f in native_report(b).findings))
        self.assertIn("not truth or deployment probability", render(b))

    def test_oversized_anchor_escalates_without_truncating_signatures(self):
        raw = copy.deepcopy(self.raw)
        raw["leads"] = []
        raw["max_source_token_proxy"] = 1
        with self.assertRaises(ValueError):
            Bundle.model_validate(raw)
        raw["state"] = "escalate-anchor-too-large"
        b = Bundle.model_validate(raw)
        self.assertNotIn(b.seed.candidate.new.code, render(b))
        self.assertIn("Full source is retained in JSON", render(b))


if __name__ == "__main__":
    unittest.main(verbosity=2)
