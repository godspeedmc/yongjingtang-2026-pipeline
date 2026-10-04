# yongjingtang-2026-pipeline

This repository contains the data pipeline and supporting project files for the 2026 Mahjong fortune calendar.

## Live demo

- https://mahjongcalendar.netlify.app

## Project overview

The project powers a Mahjong fortune calendar that supports both:

- machine_verified data
- human_verified data

It clearly separates automated cross-checking from manual review, while preserving:

- dynamic monthly queries
- fallback data support
- 50/30/20 cultural reference weighting

## Purpose

The pipeline is designed to generate and organize the calendar data used by the app, while keeping verification and weighting logic transparent and maintainable.

## Repository contents

- `app/` – application files for the calendar UI and logic
- `data/` – source and processed data used by the pipeline
- `scripts/` and related pipeline files – generation and validation workflows

## Pipeline skills and capabilities

This project is a full document-to-data pipeline for extracting, validating, and publishing 2026 Mahjong fortune calendar data. Its core capabilities include:

- PDF inspection and page discovery
- page rendering and layout normalization
- coordinate extraction for structured page regions
- daily-column detection and crop localization
- OCR on crop regions and pillar regions
- candidate generation from extracted calendar fields
- validation, calibration, exception handling, and publishability checks
- hybrid publishable dataset construction for machine_verified + human_verified records
- review workbook generation for human signoff
- CSV export and Supabase sync for downstream app consumption

In practice, the pipeline treats the source calendar pages as structured document data rather than a single flat OCR dump. It isolates layout detection, OCR, candidate assembly, and validation as separate stages so the pipeline can be reviewed, debugged, and corrected without throwing away the entire process.

## How the pipeline works

The orchestration is centered around `scripts/run_pipeline.py`, which sequences the workflow in a predictable order:

1. Page inspection and layout analysis
   - `01_inspect_pdf.py` checks the source PDF and identifies page characteristics.
   - `02_render_pages.py` renders pages for downstream analysis.
   - `03_extract_pdf_coordinates.py` maps the document geometry into usable coordinates.

2. Region detection and OCR preparation
   - `04_detect_daily_columns.py` detects the grouping/layout for each day column and generates crop rectangles.
   - `05_run_crop_ocr.py` OCRs the crop areas to extract text and signal regions that need review.
   - `05b_crop_pillar_regions.py` isolates pillar-based regions that carry important contextual information.
   - `05c_ocr_pillar_regions.py` OCRs those pillar areas for more reliable candidate extraction.

3. Candidate construction
   - `06_build_candidates.py` combines the extracted textual evidence into candidate records, turning raw OCR output into structured entries.
   - This stage is where recognized calendar values are assembled into machine-readable candidate rows.

4. Validation and quality control
   - `07_validate_candidates.py` cross-checks candidate data against rules, calibration data, and exceptions.
   - `08_build_hybrid_publishable.py` assembles the usable dataset while keeping the distinction between automatically validated and manually reviewed content.
   - `validation/` stores the downstream evidence: `validated_candidates.csv`, `publishable_candidates.csv`, `exceptions.csv`, and the validation report JSON.

5. Human review and publishing
   - `09_create_review_workbook.py` prepares a review workbook so human verifiers can inspect borderline or uncertain records.
   - `10_export_supabase_csv.py` and `11_sync_supabase.py` export and sync the final curated data for app consumption.

This means the system is intentionally layered:

- layout detection first,
- OCR and extraction second,
- candidate generation third,
- validation as a separate quality gate,
- then human review and publication.

That separation reduces error propagation and makes it easier to maintain trust between machine-generated data and human-reviewed data.

## Why this design matters

The repository is not just a scraper or OCR shortcut. It is a structured data pipeline designed around the realities of a cultural calendar and a multi-source verification model:

- machine_verified records are checked automatically
- human_verified records are reviewed when needed
- fallback data can be preserved when the original signal is weak
- the 50/30/20 reference weighting remains transparent and explainable
- dynamic month queries are supported without breaking the underlying dataset logic

## Notes

This project is focused on producing a polished, verified 2026 Mahjong fortune calendar experience with a clear distinction between algorithmic validation and human review.
