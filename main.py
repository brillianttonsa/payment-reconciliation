#!/usr/bin/env python3
"""Reconcile payment records against expected transactions.

Usage:
  python main.py expected.csv payments.csv -o reconciliation.json

Input files may be CSV or JSON. JSON can be either a list of records or an object
containing a list under `transactions`, `payments`, `records`, or `data`.

Recognized fields (aliases supported):
  transaction_id / id / order_id
  amount / total / gross_amount
  currency
  date / transaction_date / paid_at
  status
  reference / payment_reference
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ALIASES = {
    "transaction_id": ("transaction_id", "transactionId", "id", "order_id", "orderId"),
    "amount": ("amount", "total", "gross_amount", "grossAmount", "value"),
    "currency": ("currency", "currency_code", "currencyCode"),
    "date": ("date", "transaction_date", "transactionDate", "paid_at", "paidAt"),
    "status": ("status", "payment_status", "paymentStatus"),
    "reference": ("reference", "payment_reference", "paymentReference", "external_id", "externalId"),
}
SETTLED_STATUSES = {
    "captured",
    "completed",
    "paid",
    "processed",
    "settled",
    "succeeded",
    "successful",
    "success",
}


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if path.suffix.lower() != ".json":
        raise ValueError(f"{path}: input must be a .csv or .json file")

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next((payload[key] for key in ("transactions", "payments", "records", "data") if isinstance(payload.get(key), list)), None)
        if records is None:
            raise ValueError(f"{path}: expected a JSON list or an object containing transactions/payments/records/data")
    else:
        raise ValueError(f"{path}: expected a JSON list")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"{path}: every record must be an object")
    return records


def value(record: dict[str, Any], field: str) -> Any:
    for alias in ALIASES[field]:
        if alias in record and record[alias] not in (None, ""):
            return record[alias]
    return None


def amount(record: dict[str, Any]) -> Decimal | None:
    raw = value(record, "amount")
    if raw is None:
        return None
    try:
        parsed = Decimal(str(raw).replace(",", "").strip())
        if not parsed.is_finite():
            return None
        return parsed.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def normalized(record: dict[str, Any], source: str, index: int) -> dict[str, Any]:
    transaction_id = value(record, "transaction_id")
    reference = value(record, "reference")
    return {
        "transaction_id": str(transaction_id).strip() if transaction_id is not None else None,
        "reference": str(reference).strip() if reference is not None else None,
        "amount": str(amount(record)) if amount(record) is not None else None,
        "currency": str(value(record, "currency") or "").upper() or None,
        "date": value(record, "date"),
        "status": str(value(record, "status") or "").lower() or None,
        "source": source,
        "source_index": index,
        "raw": record,
    }


def reconcile(expected: list[dict[str, Any]], payments: list[dict[str, Any]], tolerance: Decimal) -> dict[str, Any]:
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError("tolerance must be a finite, non-negative amount")

    expected_rows = [normalized(row, "expected", i + 1) for i, row in enumerate(expected)]
    payment_rows = [normalized(row, "payment", i + 1) for i, row in enumerate(payments)]
    matched_payment_indexes: set[int] = set()
    transactions: list[dict[str, Any]] = []
    counts = Counter()

    for expected_row in expected_rows:
        key = expected_row["transaction_id"] or expected_row["reference"]
        candidates: list[tuple[int, dict[str, Any]]] = []
        for candidate in payment_rows:
            if candidate["source_index"] in matched_payment_indexes:
                continue
            score = 0
            if expected_row["transaction_id"] and expected_row["transaction_id"] == candidate["transaction_id"]:
                score = 2
            elif expected_row["reference"] and expected_row["reference"] == candidate["reference"]:
                score = 1
            if score:
                candidates.append((score, candidate))

        best_score = max((score for score, _ in candidates), default=0)
        best_candidates = [candidate for score, candidate in candidates if score == best_score]
        payment_row = best_candidates[0] if len(best_candidates) == 1 else None
        if payment_row is None:
            status = "ambiguous_payment" if best_candidates else "missing_payment"
            counts[status] += 1
            issue = (
                "Multiple payment records matched this transaction; review duplicate or conflicting identifiers"
                if best_candidates
                else "No payment record matched by transaction ID or reference"
            )
            transactions.append({"transaction_id": key, "status": status, "expected": expected_row, "payment": None, "issues": [issue]})
            continue

        matched_payment_indexes.add(payment_row["source_index"])
        issues: list[str] = []
        if (
            expected_row["transaction_id"]
            and payment_row["transaction_id"]
            and expected_row["transaction_id"] != payment_row["transaction_id"]
        ):
            issues.append("Transaction ID differs")
        if (
            expected_row["reference"]
            and payment_row["reference"]
            and expected_row["reference"] != payment_row["reference"]
        ):
            issues.append("Payment reference differs")
        if expected_row["amount"] is None:
            issues.append("Expected amount is missing or invalid")
        if payment_row["amount"] is None:
            issues.append("Payment amount is missing or invalid")
        if expected_row["amount"] is not None and payment_row["amount"] is not None:
            difference = abs(Decimal(expected_row["amount"]) - Decimal(payment_row["amount"]))
            if difference > tolerance:
                issues.append(f"Amount differs by {difference:.2f}")
        if expected_row["currency"] and payment_row["currency"] and expected_row["currency"] != payment_row["currency"]:
            issues.append("Currency differs")
        if payment_row["status"] and payment_row["status"] not in SETTLED_STATUSES:
            issues.append(f"Payment is not settled (status: {payment_row['status']})")
        status = "matched" if not issues else "discrepancy"
        counts[status] += 1
        transactions.append({"transaction_id": key, "status": status, "expected": expected_row, "payment": payment_row, "issues": issues})

    for payment_row in payment_rows:
        if payment_row["source_index"] not in matched_payment_indexes:
            counts["unmatched_payment"] += 1
            transactions.append({"transaction_id": payment_row["transaction_id"] or payment_row["reference"], "status": "unmatched_payment", "expected": None, "payment": payment_row, "issues": ["Payment has no matching expected transaction"]})

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "tolerance": str(tolerance),
        "summary": {
            "expected_count": len(expected_rows),
            "payment_count": len(payment_rows),
            "matched_count": counts["matched"],
            "discrepancy_count": counts["discrepancy"],
            "missing_payment_count": counts["missing_payment"],
            "ambiguous_payment_count": counts["ambiguous_payment"],
            "unmatched_payment_count": counts["unmatched_payment"],
            "reconciled_count": counts["matched"] + counts["discrepancy"],
        },
        "transactions": transactions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare expected transactions with payment records.")
    parser.add_argument("expected", nargs="?", type=Path, help="Expected transactions (.csv or .json)")
    parser.add_argument("payments", nargs="?", type=Path, help="Payment records (.csv or .json)")
    parser.add_argument("-o", "--output", type=Path, help="Write structured JSON output here; defaults to stdout")
    parser.add_argument("--tolerance", type=Decimal, default=Decimal("0.00"), help="Allowed absolute amount difference, default: 0.00")
    args = parser.parse_args()
    if args.expected is None and args.payments is None:
        sample_dir = Path(__file__).resolve().parent / "sample_data"
        args.expected = sample_dir / "expected.csv"
        args.payments = sample_dir / "payments.csv"
    elif args.expected is None or args.payments is None:
        parser.error("expected and payments must both be provided")
    try:
        if not args.tolerance.is_finite() or args.tolerance < 0:
            raise ValueError("--tolerance must be a finite, non-negative amount")
        result = reconcile(load_records(args.expected), load_records(args.payments), args.tolerance)
        output = json.dumps(result, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, InvalidOperation) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
