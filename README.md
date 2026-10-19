# Payment reconciliation tool

A small, dependency-free command-line tool for comparing expected transactions
with payment-provider or bank-export records. It matches by transaction ID, or
by payment reference when an ID is unavailable, then checks amounts, currencies,
identifiers, and payment settlement status.

## Quick start

From this directory, run the bundled sample reconciliation:

```powershell
python main.py
```

The report is printed as JSON. To use your own input files and save the report,
run:

```powershell
python main.py sample_data\expected.csv sample_data\payments.csv --output reconciliation.json
```

The JSON report includes summary counts and a result for every expected
transaction and unmatched payment. In the supplied sample data, results include
matched payments, an amount discrepancy, a failed payment, a missing payment,
and an unexpected payment.

To print your own reconciliation to the terminal instead of writing a file:

```powershell
python main.py sample_data\expected.csv sample_data\payments.csv
```

An amount difference can be allowed with `--tolerance`:

```powershell
python main.py sample_data\expected.csv sample_data\payments.csv --tolerance 0.50
```

## Input formats

Inputs can be CSV or JSON. A JSON input can be a list of objects or an object
containing a list under `transactions`, `payments`, `records`, or `data`.

The tool recognizes these fields (case-sensitive field names; common aliases
are accepted):

| Field | Accepted names |
| --- | --- |
| Transaction ID | `transaction_id`, `transactionId`, `id`, `order_id`, `orderId` |
| Amount | `amount`, `total`, `gross_amount`, `grossAmount`, `value` |
| Currency | `currency`, `currency_code`, `currencyCode` |
| Date | `date`, `transaction_date`, `transactionDate`, `paid_at`, `paidAt` |
| Status | `status`, `payment_status`, `paymentStatus` |
| Payment reference | `reference`, `payment_reference`, `paymentReference`, `external_id`, `externalId` |

Rows are matched first by an equal transaction ID, then by an equal payment
reference. Duplicate candidate payments are reported as `ambiguous_payment`
rather than choosing one arbitrarily. Rows with different amounts or currencies
are `discrepancy`; known non-settled statuses (such as `failed` or `pending`) are
also reported as discrepancies. A missing status is not assumed to be a failure.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

This tool is an aid for operational review, not an accounting system. Review
discrepancies and ambiguous matches before making ledger or settlement changes.
