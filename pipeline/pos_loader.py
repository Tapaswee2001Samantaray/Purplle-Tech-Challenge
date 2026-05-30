from __future__ import annotations

import argparse
import csv
import json
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def money(value: str | None) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def parse_pos_timestamp(order_date: str, order_time: str, timezone_name: str) -> str:
    timestamp = datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")
    return timestamp.replace(tzinfo=ZoneInfo(timezone_name)).isoformat()


def csv_to_transactions(path: Path, timezone_name: str = "Asia/Kolkata") -> list[dict]:
    grouped: dict[str, dict] = {}
    totals: dict[str, float] = defaultdict(float)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"store_id", "invoice_number", "order_id", "order_date", "order_time"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"POS CSV is missing required columns: {sorted(missing)}")
        for row in reader:
            invoice_number = row.get("invoice_number") or row.get("order_id")
            if not invoice_number:
                continue
            amount = money(row.get("total_amount")) or money(row.get("NMV")) or money(row.get("GMV"))
            if (row.get("invoice_type") or "").lower() == "return":
                amount *= -1
            totals[invoice_number] += amount
            grouped.setdefault(
                invoice_number,
                {
                    "store_id": row["store_id"],
                    "transaction_id": invoice_number,
                    "timestamp": parse_pos_timestamp(
                        row["order_date"],
                        row["order_time"],
                        timezone_name,
                    ),
                    "basket_value_inr": 0.0,
                },
            )

    transactions = []
    for transaction_id, transaction in grouped.items():
        transaction["basket_value_inr"] = round(max(totals[transaction_id], 0.0), 2)
        transactions.append(transaction)
    transactions.sort(key=lambda item: item["timestamp"])
    return transactions


def post_transactions(api_url: str, transactions: list[dict]) -> dict:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/pos/ingest",
        data=json.dumps({"transactions": transactions}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not post POS transactions to {api_url}: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Brigade POS CSV into the API.")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--timezone", default="Asia/Kolkata")
    args = parser.parse_args()

    transactions = csv_to_transactions(args.csv, args.timezone)
    print(f"Parsed {len(transactions)} POS transactions from {args.csv}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"transactions": transactions}, indent=2), encoding="utf-8")
        print(f"Wrote {args.output}")

    if args.api_url:
        print(post_transactions(args.api_url, transactions))


if __name__ == "__main__":
    main()
