from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
VALID_PILLARS = {
    STEMS[i % 10] + BRANCHES[i % 12]
    for i in range(60)
}

WEALTH_DIRECTION = {
    "甲": "東北", "乙": "東北", "丙": "西南", "丁": "西南",
    "戊": "正北", "己": "正北", "庚": "正東", "辛": "正東",
    "壬": "正南", "癸": "正南",
}
JOY_DIRECTION = {
    "甲": "東北", "乙": "西北", "丙": "西南", "丁": "正南",
    "戊": "東南", "己": "東北", "庚": "西北", "辛": "西南",
    "壬": "正南", "癸": "東南",
}
CLASH_ZODIAC = {
    "子": "馬", "丑": "羊", "寅": "猴", "卯": "雞",
    "辰": "狗", "巳": "豬", "午": "鼠", "未": "牛",
    "申": "虎", "酉": "兔", "戌": "龍", "亥": "蛇",
}
SHA_DIRECTION = {
    "子": "南", "丑": "東", "寅": "北", "卯": "西",
    "辰": "南", "巳": "東", "午": "北", "未": "西",
    "申": "南", "酉": "東", "戌": "北", "亥": "西",
}

EXPECTED_SOURCES = {
    "lunar_date_source": "yong_jing_tang",
    "day_pillar_source": "yong_jing_tang",
    "wealth_direction_source": "generic_rule",
    "joy_direction_source": "generic_rule",
    "clash_zodiac_source": "generic_rule",
    "sha_direction_source": "generic_rule",
}

OUTPUT_FIELDS = [
    "date", "edition", "source_pdf_page", "printed_page",
    "lunar_date", "day_pillar", "wealth_direction", "joy_direction",
    "clash_zodiac", "sha_direction", "lunar_date_source",
    "day_pillar_source", "wealth_direction_source", "joy_direction_source",
    "clash_zodiac_source", "sha_direction_source", "verification_status",
    "verification_notes", "reviewed_by_human", "verified_at",
    "extraction_method", "extraction_confidence",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate human-reviewed hybrid records and export a Supabase-ready CSV."
    )
    parser.add_argument(
        "--input",
        default="review/ground_truth_page_029.csv",
        help="Human-reviewed hybrid CSV.",
    )
    parser.add_argument(
        "--output",
        default="verified/yongjingtang_2026_hybrid_publishable.csv",
    )
    parser.add_argument(
        "--report",
        default="reports/hybrid_publishable_report.json",
    )
    parser.add_argument(
        "--edition",
        default="香港永經堂通勝 2026",
    )
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def clean(value) -> str:
    return str(value or "").strip()


def validate_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    input_path = resolve(root, args.input)
    output_path = resolve(root, args.output)
    report_path = resolve(root, args.report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        headers = set(reader.fieldnames or [])

    required_headers = {
        "source_pdf_page", "column_index", "date", "printed_page",
        "lunar_date", "day_pillar", "wealth_direction", "joy_direction",
        "clash_zodiac", "sha_direction", "lunar_date_source",
        "day_pillar_source", "wealth_direction_source", "joy_direction_source",
        "clash_zodiac_source", "sha_direction_source", "verification_status",
        "verification_notes",
    }
    missing_headers = sorted(required_headers - headers)
    if missing_headers:
        raise ValueError("Missing CSV columns: " + ", ".join(missing_headers))

    errors: list[str] = []
    output_rows: list[dict[str, object]] = []
    date_counts = Counter(clean(row.get("date")) for row in rows if clean(row.get("date")))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for line_number, row in enumerate(rows, start=2):
        date = clean(row.get("date"))
        pillar = clean(row.get("day_pillar"))
        prefix = f"Line {line_number} ({date or 'no date'})"
        row_errors: list[str] = []

        if not validate_date(date):
            row_errors.append("invalid date")
        if date_counts.get(date, 0) > 1:
            row_errors.append("duplicate date")
        if not clean(row.get("lunar_date")):
            row_errors.append("missing lunar_date")
        if pillar not in VALID_PILLARS:
            row_errors.append("invalid day_pillar")

        for source_field, expected_source in EXPECTED_SOURCES.items():
            actual_source = clean(row.get(source_field))
            if actual_source != expected_source:
                row_errors.append(
                    f"{source_field} must be {expected_source}, found {actual_source or 'blank'}"
                )

        if clean(row.get("verification_status")) != "human_verified":
            row_errors.append("verification_status must be human_verified")

        expected = {
            "wealth_direction": WEALTH_DIRECTION.get(pillar[:1], ""),
            "joy_direction": JOY_DIRECTION.get(pillar[:1], ""),
            "clash_zodiac": CLASH_ZODIAC.get(pillar[1:2], ""),
            "sha_direction": SHA_DIRECTION.get(pillar[1:2], ""),
        }
        for field, expected_value in expected.items():
            actual = clean(row.get(field))
            if actual != expected_value:
                row_errors.append(
                    f"{field}={actual or 'blank'} does not match generic rule {expected_value or 'unavailable'}"
                )

        if row_errors:
            errors.extend(f"{prefix}: {message}" for message in row_errors)
            continue

        output_rows.append({
            "date": date,
            "edition": args.edition,
            "source_pdf_page": clean(row.get("source_pdf_page")),
            "printed_page": clean(row.get("printed_page")),
            "lunar_date": clean(row.get("lunar_date")),
            "day_pillar": pillar,
            "wealth_direction": clean(row.get("wealth_direction")),
            "joy_direction": clean(row.get("joy_direction")),
            "clash_zodiac": clean(row.get("clash_zodiac")),
            "sha_direction": clean(row.get("sha_direction")),
            "lunar_date_source": clean(row.get("lunar_date_source")),
            "day_pillar_source": clean(row.get("day_pillar_source")),
            "wealth_direction_source": clean(row.get("wealth_direction_source")),
            "joy_direction_source": clean(row.get("joy_direction_source")),
            "clash_zodiac_source": clean(row.get("clash_zodiac_source")),
            "sha_direction_source": clean(row.get("sha_direction_source")),
            "verification_status": "human_verified",
            "verification_notes": clean(row.get("verification_notes")),
            "reviewed_by_human": True,
            "verified_at": now,
            "extraction_method": "human_reviewed_publication_fields+generic_rule_derived_fields",
            "extraction_confidence": 1.0,
        })

    report = {
        "input_file": str(input_path),
        "input_records": len(rows),
        "publishable_records": len(output_rows),
        "rejected_records": len(rows) - len(output_rows),
        "errors": errors,
        "provenance_policy": {
            "publication_fields": ["lunar_date", "day_pillar"],
            "generic_rule_fields": [
                "wealth_direction", "joy_direction", "clash_zodiac", "sha_direction"
            ],
        },
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if errors:
        print("Hybrid export blocked because validation errors were found:")
        for error in errors:
            print(f"- {error}")
        print(f"Report: {report_path}")
        raise SystemExit(1)

    output_rows.sort(key=lambda item: str(item["date"]))
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Input records: {len(rows)}")
    print(f"Publishable records: {len(output_rows)}")
    print(f"Supabase-ready CSV: {output_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
