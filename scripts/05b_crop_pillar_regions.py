from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create field-specific crops for lunar date "
            "and day pillar OCR."
        )
    )

    parser.add_argument(
        "--manifest",
        default="page-crops/all_crop_manifest.csv",
    )

    parser.add_argument(
        "--output-dir",
        default="field-crops/pillars",
    )

    parser.add_argument(
        "--pages",
        default="",
        help="Optional comma-separated pages.",
    )

    parser.add_argument(
        "--top-ratio",
        type=float,
        default=0.36,
    )

    parser.add_argument(
        "--bottom-ratio",
        type=float,
        default=0.58,
    )

    return parser.parse_args()


def resolve(
    root: Path,
    value: str
) -> Path:
    path = Path(value)

    return (
        path
        if path.is_absolute()
        else root / path
    )


def as_int(
    value,
    default: int = 0
) -> int:
    try:
        return int(float(value))
    except (
        TypeError,
        ValueError
    ):
        return default


def main() -> None:
    args = parse_args()
    root = Path.cwd()

    manifest_path = resolve(
        root,
        args.manifest
    )

    output_dir = resolve(
        root,
        args.output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    requested_pages = {
        int(value.strip())
        for value in args.pages.split(",")
        if value.strip()
    }

    with manifest_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as handle:
        rows = list(
            csv.DictReader(handle)
        )

    output_rows = []

    for row in rows:
        page = as_int(
            row.get("source_pdf_page")
        )

        column = as_int(
            row.get("column_index")
        )

        if not page or not column:
            continue

        if (
            requested_pages
            and page not in requested_pages
        ):
            continue

        source_path = resolve(
            root,
            row["crop_file"]
        )

        image = cv2.imread(
            str(source_path)
        )

        if image is None:
            print(
                f"Missing source crop: "
                f"{source_path}"
            )
            continue

        height, width = image.shape[:2]

        crop_top = int(
            round(
                height
                * args.top_ratio
            )
        )

        crop_bottom = int(
            round(
                height
                * args.bottom_ratio
            )
        )

        if crop_bottom <= crop_top:
            raise RuntimeError(
                f"Invalid pillar crop range "
                f"for page {page}, "
                f"column {column}"
            )

        pillar_crop = image[
            crop_top:crop_bottom,
            0:width
        ]

        page_dir = (
            output_dir
            / f"page_{page:03d}"
        )

        page_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        original_path = (
            page_dir
            / (
                f"col_{column:02d}"
                "_pillar_original.png"
            )
        )

        processed_path = (
            page_dir
            / (
                f"col_{column:02d}"
                "_pillar_processed.png"
            )
        )

        if not cv2.imwrite(
            str(original_path),
            pillar_crop
        ):
            raise RuntimeError(
                f"Failed to write "
                f"{original_path}"
            )

        grayscale = cv2.cvtColor(
            pillar_crop,
            cv2.COLOR_BGR2GRAY
        )

        processed = (
            cv2.adaptiveThreshold(
                grayscale,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                41,
                15,
            )
        )

        if not cv2.imwrite(
            str(processed_path),
            processed
        ):
            raise RuntimeError(
                f"Failed to write "
                f"{processed_path}"
            )

        output_rows.append(
            {
                "source_pdf_page":
                    page,

                "column_index":
                    column,

                "source_crop":
                    str(
                        source_path.relative_to(
                            root
                        )
                    ),

                "pillar_original":
                    str(
                        original_path.relative_to(
                            root
                        )
                    ),

                "pillar_processed":
                    str(
                        processed_path.relative_to(
                            root
                        )
                    ),

                "local_x0":
                    0,

                "local_y0":
                    crop_top,

                "local_x1":
                    width,

                "local_y1":
                    crop_bottom,
            }
        )

        print(
            f"Page {page}, column {column}: "
            f"pillar region "
            f"y={crop_top}-{crop_bottom}"
        )

    manifest_output = (
        output_dir
        / "pillar_crop_manifest.csv"
    )

    fieldnames = [
        "source_pdf_page",
        "column_index",
        "source_crop",
        "pillar_original",
        "pillar_processed",
        "local_x0",
        "local_y0",
        "local_x1",
        "local_y1",
    ]

    with manifest_output.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(
            output_rows
        )

    print(
        f"Pillar crop manifest: "
        f"{manifest_output}"
    )

    print(
        f"Pillar crops created: "
        f"{len(output_rows)}"
    )


if __name__ == "__main__":
    main()