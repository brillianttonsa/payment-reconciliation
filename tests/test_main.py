import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from main import load_records, reconcile


class ReconcileTests(unittest.TestCase):
    def test_running_without_arguments_reconciles_bundled_samples(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(project_dir / "main.py")],
            cwd=project_dir,
            capture_output=True,
            check=True,
            text=True,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["expected_count"], 5)
        self.assertEqual(report["summary"]["payment_count"], 5)

    def test_sample_files_cover_expected_outcomes(self) -> None:
        expected = load_records(Path("sample_data/expected.csv"))
        payments = load_records(Path("sample_data/payments.csv"))

        result = reconcile(expected, payments, Decimal("0.00"))

        self.assertEqual(
            result["summary"],
            {
                "expected_count": 5,
                "payment_count": 5,
                "matched_count": 2,
                "discrepancy_count": 2,
                "missing_payment_count": 1,
                "ambiguous_payment_count": 0,
                "unmatched_payment_count": 1,
                "reconciled_count": 4,
            },
        )
        self.assertEqual(result["transactions"][2]["status"], "matched")
        self.assertEqual(result["transactions"][3]["status"], "missing_payment")
        self.assertIn("not settled", result["transactions"][4]["issues"][0])

    def test_uses_reference_when_transaction_id_is_missing(self) -> None:
        result = reconcile(
            [{"transaction_id": "ORDER-1", "reference": "REF-1", "amount": "10.00"}],
            [{"reference": "REF-1", "amount": "10.00", "status": "paid"}],
            Decimal("0.00"),
        )

        self.assertEqual(result["transactions"][0]["status"], "matched")

    def test_ambiguous_duplicate_payments_are_not_silently_matched(self) -> None:
        result = reconcile(
            [{"transaction_id": "ORDER-1", "amount": "10.00"}],
            [
                {"transaction_id": "ORDER-1", "amount": "10.00"},
                {"transaction_id": "ORDER-1", "amount": "10.00"},
            ],
            Decimal("0.00"),
        )

        self.assertEqual(result["summary"]["ambiguous_payment_count"], 1)
        self.assertEqual(result["summary"]["unmatched_payment_count"], 2)

    def test_rejects_negative_tolerance(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            reconcile([], [], Decimal("-0.01"))


if __name__ == "__main__":
    unittest.main()
