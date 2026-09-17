from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import fitz


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a Yong Jing Tang PDF and create page metadata and a starter page manifest."
    )
    parser.add_argument(
        "--pdf",
        default="source/976852581-通勝-丙午年2026.pdf",
        help="Path to the source PDF, relative to the project root unless absolute.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Directory for inspection outputs.",
    )
    parser.add_argument(
        "--daily-start",
        type=int,
        default=4,
        help="First candidate daily page, using 1-based PDF page numbering.",
    )
    parser.add_argument(
        "--daily-end",
        type=int,
        default=51,
        help="Last candidate daily page, using 1-based PDF page numbering.",
    )
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def classify_page(page_number: int, daily_start: int, daily_end: int) -> tuple[str, str]:
    if page_number == 1:
        return "cover", "exclude"
    if page_number == 2:
        return "solar_terms", "separate"
    if page_number == 3:
        return "moon_phases", "separate"
    if daily_start <= page_number <= daily_end:
        return "daily_pages", "extract"
    return "reference_or_following_year", "exclude"


def main() -> None:
    args = parse_args()
    project_root = Path.cwd()
    pdf_path = resolve(project_root, args.pdf)
    output_dir = resolve(project_root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    document = fitz.open(pdf_path)
    pages = []

    for index, page in enumerate(document):
        page_number = index + 1
        width = float(page.rect.width)
        height = float(page.rect.height)
        words = page.get_text("words")
        plain_text = page.get_text("text").strip()
        image_info = page.get_images(full=True)
        section, action = classify_page(
            page_number,
            args.daily_start,
            args.daily_end,
        )

        pages.append(
            {
                "source_pdf_page": page_number,
                "section": section,
                "action": action,
                "width_points": round(width, 2),
                "height_points": round(height, 2),
                "rotation": int(page.rotation),
                "word_count": len(words),
                "text_character_count": len(plain_text),
                "embedded_image_count": len(image_info),
                "has_text_layer": bool(plain_text),
                "portrait": height >= width,
            }
        )

    metadata = {
        "pdf_file": str(pdf_path),
        "page_count": len(document),
        "metadata": document.metadata,
        "candidate_daily_page_range": {
            "start": args.daily_start,
            "end": args.daily_end,
        },
        "pages": pages,
    }

    json_path = output_dir / "pdf_inspection.json"
    json_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = output_dir / "page_inspection.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pages[0].keys()))
        writer.writeheader()
        writer.writerows(pages)

    manifest_path = project_root / "config" / "page_manifest.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "source_pdf_page",
            "section",
            "expected_period",
            "action",
            "reviewed",
            "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in pages:
            expected_period = "2026" if item["action"] != "exclude" else ""
            notes = "Candidate classification. Confirm visually before full extraction."
            writer.writerow(
                {
                    "source_pdf_page": item["source_pdf_page"],
                    "section": item["section"],
                    "expected_period": expected_period,
                    "action": item["action"],
                    "reviewed": "no",
                    "notes": notes,
                }
            )

    print(f"PDF: {pdf_path}")
    print(f"Pages: {len(document)}")
    print(f"Inspection JSON: {json_path}")
    print(f"Inspection CSV: {csv_path}")
    print(f"Starter manifest: {manifest_path}")
    print("Important: confirm the daily page range visually before running full extraction.")


if __name__ == "__main__":
    main()
