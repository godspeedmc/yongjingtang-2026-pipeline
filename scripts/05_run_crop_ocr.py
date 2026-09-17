from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import pytesseract
from pytesseract import Output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run multiple Tesseract OCR passes over daily-column crops and "
            "save one JSON result per crop and PSM mode."
        )
    )
    parser.add_argument(
        "--manifest",
        default="page-crops/all_crop_manifest.csv",
        help="Combined crop manifest created by 04_detect_daily_columns.py.",
    )
    parser.add_argument(
        "--output-dir",
        default="ocr-results",
        help="Directory for OCR JSON files and summary CSV files.",
    )
    parser.add_argument(
        "--languages",
        default="chi_tra+eng",
        help="Tesseract language expression.",
    )
    parser.add_argument(
        "--psm",
        default="4,6,11",
        help="Comma-separated Tesseract page segmentation modes.",
    )
    parser.add_argument(
        "--oem",
        type=int,
        default=1,
        help="Tesseract OCR engine mode. Default 1 uses the LSTM engine.",
    )
    parser.add_argument(
        "--image-kind",
        choices=["original", "processed", "both"],
        default="both",
        help="OCR original crops, processed crops, or both.",
    )
    parser.add_argument(
        "--pages",
        default="",
        help="Optional comma-separated PDF pages, for example 4,24,36.",
    )
    parser.add_argument(
        "--minimum-token-confidence",
        type=float,
        default=0.0,
        help="Exclude tokens with confidence below this value from joined text.",
    )
    parser.add_argument(
        "--tesseract-cmd",
        default="",
        help="Optional full path to tesseract executable on Windows.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing OCR JSON files.",
    )
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def configure_tesseract(explicit_command: str) -> str:
    candidates = []
    if explicit_command:
        candidates.append(explicit_command)

    discovered = shutil.which("tesseract")
    if discovered:
        candidates.append(discovered)

    if sys.platform.startswith("win"):
        candidates.extend(
            [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
        )

    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(path)
            return str(path)

    raise FileNotFoundError(
        "Tesseract executable was not found. Install Tesseract or pass "
        "--tesseract-cmd with the full executable path."
    )


def installed_languages() -> set[str]:
    result = subprocess.run(
        [pytesseract.pytesseract.tesseract_cmd, "--list-langs"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Unable to list Tesseract languages:\n"
            + (result.stderr or result.stdout)
        )
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and "List of available languages" not in line
    }


def validate_languages(expression: str, available: set[str]) -> None:
    requested = {part.strip() for part in expression.split("+") if part.strip()}
    missing = sorted(requested - available)
    if missing:
        raise RuntimeError(
            "Missing Tesseract language data: "
            + ", ".join(missing)
            + ". Available languages: "
            + ", ".join(sorted(available))
        )


def load_manifest(path: Path, requested_pages: set[int]) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Crop manifest not found: {path}")

    selected = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                page = int(row.get("source_pdf_page", ""))
                column = int(row.get("column_index", ""))
            except ValueError:
                continue

            crop_file = row.get("crop_file", "").strip()
            if not crop_file:
                continue
            if requested_pages and page not in requested_pages:
                continue

            row["source_pdf_page"] = str(page)
            row["column_index"] = str(column)
            selected.append(row)

    selected.sort(
        key=lambda row: (
            int(row["source_pdf_page"]),
            int(row["column_index"]),
        )
    )
    return selected


def image_paths(root: Path, crop_value: str, image_kind: str) -> list[tuple[str, Path]]:
    original = resolve(root, crop_value)
    processed = original.with_name(
        original.name.replace("_original.png", "_processed.png")
    )

    candidates = []
    if image_kind in {"original", "both"}:
        candidates.append(("original", original))
    if image_kind in {"processed", "both"}:
        candidates.append(("processed", processed))
    return candidates


def safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def run_ocr(
    image,
    languages: str,
    psm: int,
    oem: int,
    minimum_token_confidence: float,
) -> dict[str, Any]:
    config = f"--oem {oem} --psm {psm} preserve_interword_spaces=1"
    data = pytesseract.image_to_data(
        image,
        lang=languages,
        config=config,
        output_type=Output.DICT,
    )

    tokens = []
    accepted_text = []
    confidences = []

    token_count = len(data.get("text", []))
    for index in range(token_count):
        text = str(data["text"][index] or "").strip()
        confidence = safe_float(data.get("conf", [None] * token_count)[index])

        token = {
            "text": text,
            "confidence": confidence,
            "left": int(data.get("left", [0] * token_count)[index]),
            "top": int(data.get("top", [0] * token_count)[index]),
            "width": int(data.get("width", [0] * token_count)[index]),
            "height": int(data.get("height", [0] * token_count)[index]),
            "page_num": int(data.get("page_num", [0] * token_count)[index]),
            "block_num": int(data.get("block_num", [0] * token_count)[index]),
            "paragraph_num": int(data.get("par_num", [0] * token_count)[index]),
            "line_num": int(data.get("line_num", [0] * token_count)[index]),
            "word_num": int(data.get("word_num", [0] * token_count)[index]),
        }
        tokens.append(token)

        if text and confidence is not None:
            confidences.append(confidence)
            if confidence >= minimum_token_confidence:
                accepted_text.append(text)

    joined_text = "\n".join(accepted_text)
    positive_confidences = [value for value in confidences if value >= 0]

    return {
        "text": joined_text,
        "mean_confidence": (
            round(statistics.fmean(positive_confidences), 3)
            if positive_confidences
            else None
        ),
        "median_confidence": (
            round(statistics.median(positive_confidences), 3)
            if positive_confidences
            else None
        ),
        "minimum_confidence": (
            round(min(positive_confidences), 3)
            if positive_confidences
            else None
        ),
        "maximum_confidence": (
            round(max(positive_confidences), 3)
            if positive_confidences
            else None
        ),
        "recognized_token_count": len(positive_confidences),
        "accepted_token_count": len(accepted_text),
        "tokens": tokens,
        "tesseract_config": config,
    }


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    manifest_path = resolve(root, args.manifest)
    output_dir = resolve(root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    executable = configure_tesseract(args.tesseract_cmd)
    available = installed_languages()
    validate_languages(args.languages, available)

    psm_modes = []
    for value in args.psm.split(","):
        value = value.strip()
        if value:
            psm_modes.append(int(value))
    if not psm_modes:
        raise ValueError("At least one PSM mode is required.")

    requested_pages = {
        int(value.strip())
        for value in args.pages.split(",")
        if value.strip()
    }
    rows = load_manifest(manifest_path, requested_pages)
    if not rows:
        raise SystemExit("No crop rows selected from the manifest.")

    summary_rows = []
    failures = []

    print(f"Tesseract: {executable}")
    print(f"Languages: {args.languages}")
    print(f"PSM modes: {psm_modes}")
    print(f"Selected crops: {len(rows)}")

    for manifest_row in rows:
        page = int(manifest_row["source_pdf_page"])
        column = int(manifest_row["column_index"])

        for kind, image_path in image_paths(root, manifest_row["crop_file"], args.image_kind):
            if not image_path.exists():
                failures.append(
                    {
                        "source_pdf_page": page,
                        "column_index": column,
                        "image_kind": kind,
                        "image_file": str(image_path),
                        "error": "Image file not found",
                    }
                )
                continue

            image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                failures.append(
                    {
                        "source_pdf_page": page,
                        "column_index": column,
                        "image_kind": kind,
                        "image_file": str(image_path),
                        "error": "OpenCV could not read image",
                    }
                )
                continue

            for psm in psm_modes:
                output_name = f"page_{page:03d}_col_{column:02d}_{kind}_psm{psm}.json"
                output_path = output_dir / output_name

                if output_path.exists() and not args.overwrite:
                    try:
                        existing = json.loads(output_path.read_text(encoding="utf-8"))
                        summary_rows.append(
                            {
                                "source_pdf_page": page,
                                "column_index": column,
                                "image_kind": kind,
                                "psm": psm,
                                "mean_confidence": existing.get("mean_confidence"),
                                "median_confidence": existing.get("median_confidence"),
                                "recognized_token_count": existing.get("recognized_token_count"),
                                "accepted_token_count": existing.get("accepted_token_count"),
                                "text_character_count": len(existing.get("text", "")),
                                "column_warning": manifest_row.get("column_warning", ""),
                                "ocr_json": str(output_path.relative_to(root)),
                                "status": "existing",
                            }
                        )
                    except Exception as error:
                        failures.append(
                            {
                                "source_pdf_page": page,
                                "column_index": column,
                                "image_kind": kind,
                                "image_file": str(image_path),
                                "error": f"Existing JSON unreadable: {error}",
                            }
                        )
                    continue

                try:
                    result = run_ocr(
                        image=image,
                        languages=args.languages,
                        psm=psm,
                        oem=args.oem,
                        minimum_token_confidence=args.minimum_token_confidence,
                    )

                    payload = {
                        "source_pdf_page": page,
                        "column_index": column,
                        "image_kind": kind,
                        "image_file": str(image_path.relative_to(root)),
                        "psm": psm,
                        "ocr_languages": args.languages,
                        "column_warning": str(
                            manifest_row.get("column_warning", "")
                        ).lower() in {"true", "1", "yes"},
                        "crop_coordinates": {
                            "x0": manifest_row.get("x0", ""),
                            "y0": manifest_row.get("y0", ""),
                            "x1": manifest_row.get("x1", ""),
                            "y1": manifest_row.get("y1", ""),
                        },
                        **result,
                    }
                    output_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                    summary_rows.append(
                        {
                            "source_pdf_page": page,
                            "column_index": column,
                            "image_kind": kind,
                            "psm": psm,
                            "mean_confidence": result["mean_confidence"],
                            "median_confidence": result["median_confidence"],
                            "recognized_token_count": result["recognized_token_count"],
                            "accepted_token_count": result["accepted_token_count"],
                            "text_character_count": len(result["text"]),
                            "column_warning": manifest_row.get("column_warning", ""),
                            "ocr_json": str(output_path.relative_to(root)),
                            "status": "created",
                        }
                    )
                    print(
                        f"Page {page}, column {column}, {kind}, PSM {psm}: "
                        f"mean confidence={result['mean_confidence']}, "
                        f"tokens={result['accepted_token_count']}"
                    )
                except Exception as error:
                    failures.append(
                        {
                            "source_pdf_page": page,
                            "column_index": column,
                            "image_kind": kind,
                            "image_file": str(image_path),
                            "psm": psm,
                            "error": str(error),
                        }
                    )
                    print(
                        f"FAILED page {page}, column {column}, {kind}, PSM {psm}: {error}"
                    )

    summary_path = output_dir / "ocr_summary.csv"
    summary_fields = [
        "source_pdf_page",
        "column_index",
        "image_kind",
        "psm",
        "mean_confidence",
        "median_confidence",
        "recognized_token_count",
        "accepted_token_count",
        "text_character_count",
        "column_warning",
        "ocr_json",
        "status",
    ]
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    failures_path = output_dir / "ocr_failures.csv"
    failure_fields = [
        "source_pdf_page",
        "column_index",
        "image_kind",
        "image_file",
        "psm",
        "error",
    ]
    with failures_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=failure_fields)
        writer.writeheader()
        for failure in failures:
            writer.writerow({field: failure.get(field, "") for field in failure_fields})

    print(f"OCR summary: {summary_path}")
    print(f"OCR failures: {failures_path}")
    print(f"Successful OCR passes: {len(summary_rows)}")
    print(f"Failures: {len(failures)}")
    print(
        "Confidence is retained as one extraction signal only. "
        "Do not convert it directly into machine_verified status."
    )


if __name__ == "__main__":
    main()
