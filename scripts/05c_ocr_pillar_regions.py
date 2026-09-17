from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import cv2
import pytesseract

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
VALID_PILLARS = {
    STEMS[i % 10] + BRANCHES[i % 12]
    for i in range(60)
}
PILLAR_PATTERN = re.compile(rf"[{STEMS}][{BRANCHES}]")


def parse_args():
    p = argparse.ArgumentParser(description="OCR field-specific lunar-day and day-pillar crops.")
    p.add_argument("--manifest", default="field-crops/pillars/pillar_crop_manifest.csv")
    p.add_argument("--output-dir", default="ocr-results/pillars")
    p.add_argument("--pages", default="")
    p.add_argument("--languages", default="chi_tra_vert")
    p.add_argument("--psm", default="5,11")
    p.add_argument("--scale", type=float, default=2.0)
    p.add_argument("--tesseract-cmd", default=r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    return p.parse_args()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def extract_pillars(text: str) -> list[str]:
    return list(dict.fromkeys(
        x for x in PILLAR_PATTERN.findall(clean_text(text))
        if x in VALID_PILLARS
    ))


def variants(image, scale: float):
    up = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
    otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 51, 13
    )
    # Light closing joins broken strokes without aggressively expanding characters.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    closed = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel)
    return {
        "upscaled": up,
        "otsu": otsu,
        "adaptive": adaptive,
        "closed": closed,
    }


def main():
    args = parse_args()
    root = Path.cwd()
    manifest = root / args.manifest
    out = root / args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    exe = Path(args.tesseract_cmd)
    if not exe.exists():
        found = shutil.which("tesseract")
        if not found:
            raise FileNotFoundError("Tesseract not found. Use --tesseract-cmd.")
        exe = Path(found)
    pytesseract.pytesseract.tesseract_cmd = str(exe)

    requested = {int(x) for x in args.pages.split(",") if x.strip()}
    psms = [int(x) for x in args.psm.split(",") if x.strip()]

    with manifest.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    summary = []
    for row in rows:
        page = int(row["source_pdf_page"])
        col = int(row["column_index"])
        if requested and page not in requested:
            continue

        source = root / row["pillar_original"]
        image = cv2.imread(str(source))
        if image is None:
            print(f"Missing image: {source}")
            continue

        candidates = []
        passes = []
        page_dir = out / f"page_{page:03d}"
        page_dir.mkdir(parents=True, exist_ok=True)

        for variant_name, variant in variants(image, args.scale).items():
            variant_path = page_dir / f"col_{col:02d}_{variant_name}.png"
            cv2.imwrite(str(variant_path), variant)
            for psm in psms:
                config = f"--oem 1 --psm {psm} preserve_interword_spaces=1"
                text = pytesseract.image_to_string(
                    variant, lang=args.languages, config=config
                )
                found = extract_pillars(text)
                candidates.extend(found)
                passes.append({
                    "variant": variant_name,
                    "psm": psm,
                    "text": text,
                    "pillars": found,
                })

        votes = Counter(candidates)
        ranked = sorted(votes.items(), key=lambda x: (-x[1], x[0]))
        best = ranked[0][0] if ranked else ""
        best_votes = ranked[0][1] if ranked else 0

        payload = {
            "source_pdf_page": page,
            "column_index": col,
            "source_crop": row["pillar_original"],
            "language": args.languages,
            "psm_modes": psms,
            "scale": args.scale,
            "day_pillar_candidates": [x for x, _ in ranked],
            "vote_counts": dict(ranked),
            "top_candidate": best or None,
            "top_votes": best_votes,
            "passes": passes,
        }
        json_path = page_dir / f"col_{col:02d}_pillar_ocr.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        summary.append({
            "source_pdf_page": page,
            "column_index": col,
            "day_pillar_top": best,
            "day_pillar_votes": best_votes,
            "candidate_count": len(ranked),
            "result_json": str(json_path.relative_to(root)),
        })
        print(f"Page {page}, column {col}: pillar={best or '--'}, votes={best_votes}")

    summary_path = out / "pillar_ocr_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["source_pdf_page", "column_index", "day_pillar_top", "day_pillar_votes", "candidate_count", "result_json"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(summary)

    print(f"Summary: {summary_path}")
    print(f"Rows processed: {len(summary)}")


if __name__ == "__main__":
    main()
