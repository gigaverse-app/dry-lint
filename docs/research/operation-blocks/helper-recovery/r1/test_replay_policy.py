"""Boundary and label checks for the provider-free canonical reporting rule."""
import unittest
from replay import reports


class ReportPolicyTests(unittest.TestCase):
    def test_label_and_boundary(self):
        for label, score, expected in [
            ("separate", 1.0, False), ("duplicate", .7999, False),
            ("duplicate", .8, True), ("drifted", .8, True),
        ]:
            with self.subTest(label=label, score=score):
                self.assertEqual(reports(dict(label=label, score=score)), expected)

    def test_unknown_and_model_assessment_do_not_report(self):
        self.assertFalse(reports(None))
        self.assertFalse(reports(dict(label="duplicate", score=1, model_assessment={})))

    def test_unexpected_escalation_is_not_silently_reinterpreted(self):
        with self.assertRaises(AssertionError):
            reports(dict(label="duplicate", score=1, second_opinion={}))


if __name__ == "__main__":
    unittest.main()
