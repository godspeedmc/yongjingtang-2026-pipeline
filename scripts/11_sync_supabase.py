from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg import sql
except ImportError as exc:
    raise SystemExit(
        "Missing dependency. Install it with: pip install 'psycopg[binary]'"
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically replace a Supabase/Postgres date range from the "
            "verified Yong Jing Tang publishable CSV."
        )
    )
    parser.add_argument(
        "--csv",
        default="verified/yongjingtang_2026_hybrid_publishable.csv",
        help="Publishable CSV created by 08_build_hybrid_publishable.py.",
    )
    parser.add_argument("--schema", default="public")
    parser.add_argument("--table", default="tung_shing_daily")
    parser.add_argument(
        "--database-url-env",
        default="SUPABASE_DB_URL",
        help="Environment variable containing the Postgres connection string.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the CSV and show the replacement range without changing data.",
    )
    parser.add_argument(
        "--confirm-replace",
        action="store_true",
        help="Required for a real database update.",
    )
    return parser.parse_args()


def clean(value: Any) -> str:
    return str(value or "").strip()


def parse_bool(value: str) -> bool:
    normalized = clean(value).lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def parse_value(column: str, value: str) -> Any:
    value = clean(value)
    if value == "":
        return None
    if column == "date":
        return date.fromisoformat(value)
    if column == "source_pdf_page":
        return int(value)
    if column == "reviewed_by_human":
        return parse_bool(value)
    if column == "extraction_confidence":
        return float(value)
    if column == "verified_at":
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def load_and_validate(csv_path: Path) -> tuple[list[str], list[dict[str, Any]], date, date]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        raw_rows = list(reader)

    required = {
        "date",
        "lunar_date",
        "day_pillar",
        "wealth_direction",
        "joy_direction",
        "clash_zodiac",
        "sha_direction",
        "verification_status",
        "reviewed_by_human",
    }
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing))
    if not raw_rows:
        raise ValueError("The CSV contains no data rows.")

    rows: list[dict[str, Any]] = []
    seen_dates: set[date] = set()

    for line_number, raw in enumerate(raw_rows, start=2):
        row = {column: parse_value(column, raw.get(column, "")) for column in headers}
        row_date = row["date"]
        if row_date in seen_dates:
            raise ValueError(f"Duplicate date on line {line_number}: {row_date}")
        seen_dates.add(row_date)

        if row.get("verification_status") not in {"human_verified", "machine_verified"}:
            raise ValueError(
                f"Line {line_number}: non-publishable verification_status "
                f"{row.get('verification_status')!r}"
            )
        if row.get("reviewed_by_human") is not True:
            raise ValueError(
                f"Line {line_number}: reviewed_by_human must be true for this sync workflow."
            )
        rows.append(row)

    rows.sort(key=lambda item: item["date"])
    start_date = rows[0]["date"]
    end_date = rows[-1]["date"]
    expected_count = (end_date - start_date).days + 1

    if len(rows) != expected_count:
        actual_dates = {row["date"] for row in rows}
        missing_dates = []
        cursor = start_date
        while cursor <= end_date:
            if cursor not in actual_dates:
                missing_dates.append(cursor.isoformat())
            cursor += timedelta(days=1)
        raise ValueError(
            "CSV date range is not continuous. Missing dates: "
            + ", ".join(missing_dates)
        )

    return headers, rows, start_date, end_date


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = root / csv_path

    headers, rows, start_date, end_date = load_and_validate(csv_path)

    print(f"CSV: {csv_path}")
    print(f"Validated rows: {len(rows)}")
    print(f"Replacement range: {start_date} through {end_date}")
    print("Date sequence: continuous")

    if args.dry_run:
        print("Dry run complete. No database changes were made.")
        return

    if not args.confirm_replace:
        raise SystemExit(
            "Database update blocked. Re-run with --confirm-replace after reviewing the dry run."
        )

    database_url = clean(os.environ.get(args.database_url_env))
    if not database_url:
        raise SystemExit(
            f"Environment variable {args.database_url_env} is not set. "
            "Store the Supabase Postgres connection string in that variable."
        )

    table_identifier = sql.Identifier(args.schema, args.table)
    columns_sql = sql.SQL(", ").join(sql.Identifier(column) for column in headers)
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in headers)

    delete_query = sql.SQL(
        "DELETE FROM {} WHERE date BETWEEN %s AND %s"
    ).format(table_identifier)
    insert_query = sql.SQL(
        "INSERT INTO {} ({}) VALUES ({})"
    ).format(table_identifier, columns_sql, placeholders)
    verify_query = sql.SQL(
        "SELECT date FROM {} WHERE date BETWEEN %s AND %s ORDER BY date"
    ).format(table_identifier)

    values = [tuple(row[column] for column in headers) for row in rows]

    # One transaction: any delete, insert, or verification failure rolls everything back.
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(delete_query, (start_date, end_date))
                deleted_count = cursor.rowcount

                cursor.executemany(insert_query, values)

                cursor.execute(verify_query, (start_date, end_date))
                database_dates = [record[0] for record in cursor.fetchall()]
                expected_dates = [row["date"] for row in rows]

                if database_dates != expected_dates:
                    raise RuntimeError(
                        "Post-insert verification failed. The transaction will be rolled back."
                    )

    print(f"Deleted previous rows in range: {deleted_count}")
    print(f"Inserted rows: {len(rows)}")
    print("Post-insert verification: passed")
    print("Supabase sync completed atomically.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
