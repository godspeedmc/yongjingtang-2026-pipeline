from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(
        description="Run automated Yong Jing Tang extraction stages for selected PDF pages."
    )
    p.add_argument("--pages", required=True, help="Comma-separated pages, for example 32,33,34.")
    p.add_argument("--tesseract-cmd", default=r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    p.add_argument("--languages", default="chi_tra_vert")
    p.add_argument("--crop-only", action="store_true", help="Run crop detection only, then stop for visual review.")
    p.add_argument("--skip-crop", action="store_true", help="Use existing reviewed crops.")
    p.add_argument("--skip-ocr", action="store_true")
    p.add_argument("--skip-pillars", action="store_true")
    p.add_argument("--skip-candidates", action="store_true")
    p.add_argument("--create-review-workbook", action="store_true")
    return p.parse_args()


def run(command: list[str], root: Path) -> None:
    print("\n> " + " ".join(command))
    result = subprocess.run(command, cwd=root)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main():
    args = parse_args()
    root = Path.cwd()
    python = sys.executable
    scripts = root / "scripts"

    required = [
        "04_detect_daily_columns.py", "05_run_crop_ocr.py",
        "05b_crop_pillar_regions.py", "05c_ocr_pillar_regions.py",
        "06_build_candidates.py", "09_create_review_workbook.py",
    ]
    missing = [name for name in required if not (scripts / name).exists()]
    if missing:
        raise FileNotFoundError("Missing scripts: " + ", ".join(missing))

    if not args.skip_crop:
        run([python, str(scripts / "04_detect_daily_columns.py"), "--pages", args.pages, "--debug"], root)

    if args.crop_only:
        print("\nStopped after crop detection. Review debug_crop_rectangles.png before continuing.")
        return

    if not args.skip_ocr:
        run([
            python, str(scripts / "05_run_crop_ocr.py"),
            "--pages", args.pages, "--languages", args.languages,
            "--psm", "5,6", "--image-kind", "both",
            "--tesseract-cmd", args.tesseract_cmd, "--overwrite",
        ], root)

    if not args.skip_pillars:
        run([python, str(scripts / "05b_crop_pillar_regions.py"), "--pages", args.pages], root)
        run([
            python, str(scripts / "05c_ocr_pillar_regions.py"),
            "--pages", args.pages, "--languages", args.languages,
            "--psm", "5,11", "--scale", "2",
            "--tesseract-cmd", args.tesseract_cmd,
        ], root)

    if not args.skip_candidates:
        run([
            python, str(scripts / "06_build_candidates.py"),
            "--pages", args.pages, "--psm", "5,6",
            "--image-kinds", "original,processed",
        ], root)

    if args.create_review_workbook:
        run([
            python, str(scripts / "09_create_review_workbook.py"),
            "--pages", args.pages,
        ], root)

    print("\nAutomated stages completed. Human crop/date/lunar-date/pillar review is still required before export.")


if __name__ == "__main__":
    main()
