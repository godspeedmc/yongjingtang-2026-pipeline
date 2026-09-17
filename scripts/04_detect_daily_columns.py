from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect and crop vertical daily columns from rendered Yong Jing Tang pages."
    )
    parser.add_argument("--manifest", default="config/page_manifest.csv")
    parser.add_argument("--templates", default="config/crop_templates.json")
    parser.add_argument("--rendered-dir", default="rendered-pages")
    parser.add_argument("--output-dir", default="page-crops")
    parser.add_argument(
        "--pages",
        default="",
        help="Optional comma-separated 1-based pages, for example 4,24,36.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save separator-detection diagnostic images.",
    )
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Crop template file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_extract_pages(path: Path) -> list[int]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    pages = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)

        lines = sample.splitlines()
        header = lines[0] if lines else ""
        delimiter = "\t" if "\t" in header else ","
        reader = csv.DictReader(handle, delimiter=delimiter)

        required_columns = {"source_pdf_page", "action"}
        actual_columns = set(reader.fieldnames or [])

        if not required_columns.issubset(actual_columns):
            raise ValueError(
                "Manifest must contain separate source_pdf_page and action columns. "
                f"Found: {reader.fieldnames}"
            )

        for row in reader:
            if row.get("action", "").strip() == "extract":
                pages.append(int(row["source_pdf_page"]))

    return pages


def page_template(templates: dict, page_number: int) -> dict:
    base = dict(templates.get("default_daily_page", {}))
    exception = templates.get("layout_exceptions", {}).get(str(page_number), {})
    base.update(exception)
    return base


def consecutive_groups(values: np.ndarray, tolerance: int = 2) -> list[list[int]]:
    if len(values) == 0:
        return []

    groups = [[int(values[0])]]

    for value in values[1:]:
        value = int(value)

        if value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])

    return groups


def detect_vertical_separators(
    roi_gray: np.ndarray,
    minimum_line_ratio: float,
    projection_threshold_ratio: float,
) -> tuple[list[int], np.ndarray, np.ndarray]:
    binary = cv2.adaptiveThreshold(
        roi_gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        41,
        15,
    )

    kernel_height = max(
        25,
        int(roi_gray.shape[0] * minimum_line_ratio),
    )

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, kernel_height),
    )

    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        vertical_kernel,
    )

    projection = vertical.sum(axis=0).astype(np.float64)

    threshold = (
        projection.max() * projection_threshold_ratio
        if projection.max()
        else 0
    )

    candidates = np.where(projection >= threshold)[0]
    groups = consecutive_groups(candidates)

    centers = [
        int(round(sum(group) / len(group)))
        for group in groups
        if group
    ]

    return centers, binary, vertical


def equally_spaced_boundaries(width: int, column_count: int) -> list[int]:
    return [
        int(round(value))
        for value in np.linspace(0, width, column_count + 1)
    ]


def choose_boundaries(
    width: int,
    expected_columns: int,
    detected_centers: list[int],
    snap_tolerance_ratio: float,
) -> tuple[list[int], str, list[str]]:
    warnings = []

    minimum_gap = max(
        4,
        int(width * 0.01)
    )

    usable_centers = []

    for center in sorted(
        set(detected_centers)
    ):
        center = max(
            0,
            min(width, center)
        )

        if (
            not usable_centers
            or center - usable_centers[-1]
            >= minimum_gap
        ):
            usable_centers.append(center)

    required_boundaries = (
        expected_columns + 1
    )

    # Best case:
    # The detector found precisely the number
    # of separators required for the page.
    if (
        len(usable_centers)
        == required_boundaries
    ):
        return (
            usable_centers,
            "detected_separators",
            warnings
        )

    # The outer page boundaries may not appear
    # as detected separator lines.
    interior_centers = [
        center
        for center in usable_centers
        if center > minimum_gap
        and center < width - minimum_gap
    ]

    if (
        len(interior_centers)
        == expected_columns - 1
    ):
        return (
            [0]
            + interior_centers
            + [width],
            "detected_interior_separators",
            warnings
        )

    expected = (
        equally_spaced_boundaries(
            width,
            expected_columns
        )
    )

    tolerance = max(
        5,
        int(
            width
            * snap_tolerance_ratio
        )
    )

    selected = [0]
    used_centers = set()

    for target in expected[1:-1]:
        nearby = [
            center
            for center in usable_centers
            if center not in used_centers
            and abs(center - target)
            <= tolerance
        ]

        if nearby:
            chosen = min(
                nearby,
                key=lambda center:
                    abs(center - target)
            )

            selected.append(chosen)
            used_centers.add(chosen)
        else:
            selected.append(target)

            warnings.append(
                "No separator near "
                f"expected x={target}; "
                "used template boundary."
            )

    selected.append(width)
    selected = sorted(set(selected))

    if (
        len(selected)
        != required_boundaries
    ):
        warnings.append(
            "Boundary count was invalid; "
            "used equal-width fallback."
        )

        return (
            expected,
            "equal_width_fallback",
            warnings
        )

    for index in range(
        len(selected) - 1
    ):
        if (
            selected[index + 1]
            - selected[index]
            < minimum_gap
        ):
            warnings.append(
                "Detected boundaries were "
                "too close together; "
                "used equal-width fallback."
            )

            return (
                expected,
                "equal_width_fallback",
                warnings
            )

    return (
        selected,
        "hybrid_template",
        warnings
    )



def validate_crop_rows(
    page_number: int,
    page_rows: list[dict],
    expected_columns: int,
) -> None:
    if len(page_rows) != expected_columns:
        raise RuntimeError(
            f"Page {page_number}: expected {expected_columns} crops "
            f"but created {len(page_rows)}."
        )

    coordinate_sets = {
        (
            int(row["x0"]),
            int(row["y0"]),
            int(row["x1"]),
            int(row["y1"]),
        )
        for row in page_rows
    }

    if len(coordinate_sets) != len(page_rows):
        raise RuntimeError(
            f"Page {page_number}: duplicate crop coordinates detected."
        )

    for row in page_rows:
        if int(row["x1"]) <= int(row["x0"]):
            raise RuntimeError(
                f"Page {page_number}, column {row['column_index']}: "
                "crop width is invalid."
            )

        if int(row["y1"]) <= int(row["y0"]):
            raise RuntimeError(
                f"Page {page_number}, column {row['column_index']}: "
                "crop height is invalid."
            )

    physical_rows = sorted(
        page_rows,
        key=lambda row: int(row["x0"]),
    )

    for index in range(len(physical_rows) - 1):
        current = physical_rows[index]
        following = physical_rows[index + 1]

        if int(current["x1"]) > int(following["x0"]):
            raise RuntimeError(
                f"Page {page_number}: column {current['column_index']} "
                f"overlaps column {following['column_index']}. "
                f"Ranges: {current['x0']}-{current['x1']} and "
                f"{following['x0']}-{following['x1']}"
            )

    automatic_rows = [
        row
        for row in page_rows
        if row["detection_method"] != "manual_override"
    ]

    automatic_vertical_ranges = {
        (int(row["y0"]), int(row["y1"]))
        for row in automatic_rows
    }

    if len(automatic_vertical_ranges) > 1:
        raise RuntimeError(
            f"Page {page_number}: inconsistent automatic vertical ranges: "
            f"{sorted(automatic_vertical_ranges)}"
        )


def write_image(path: Path, image: np.ndarray, description: str) -> None:
    if image is None or image.size == 0:
        raise RuntimeError(f"Cannot write empty {description}: {path}")

    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Failed to write {description}: {path}")


def main() -> None:
    args = parse_args()
    root = Path.cwd()

    manifest_path = resolve(root, args.manifest)
    template_path = resolve(root, args.templates)
    rendered_dir = resolve(root, args.rendered_dir)
    output_dir = resolve(root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    templates = load_json(template_path)
    pages = load_extract_pages(manifest_path)

    if args.pages.strip():
        requested = {
            int(value.strip())
            for value in args.pages.split(",")
            if value.strip()
        }

        pages = [
            page
            for page in pages
            if page in requested
        ]

    if not pages:
        raise SystemExit(
            "No pages selected. Check the manifest or --pages argument."
        )

    overall_manifest = []

    for page_number in pages:
        image_path = rendered_dir / f"page_{page_number:03d}.png"
        image = cv2.imread(str(image_path))

        if image is None:
            overall_manifest.append(
                {
                    "source_pdf_page": page_number,
                    "column_index": "",
                    "x0": "",
                    "y0": "",
                    "x1": "",
                    "y1": "",
                    "reading_order": "",
                    "detection_method": "missing_page",
                    "column_warning": True,
                    "warning_notes": f"Rendered image not found: {image_path}",
                    "crop_file": "",
                }
            )
            continue

        settings = page_template(templates, page_number)

        expected_columns = int(settings.get("column_count", 8))
        reading_order = settings.get("reading_order", "right_to_left")
        header_exclusion = float(settings.get("header_exclusion", 0.08))
        footer_exclusion = float(settings.get("footer_exclusion", 0.08))
        left_exclusion = float(settings.get("left_exclusion", 0.02))
        right_exclusion = float(settings.get("right_exclusion", 0.02))
        minimum_line_ratio = float(settings.get("minimum_line_ratio", 0.45))
        projection_threshold_ratio = float(
            settings.get("projection_threshold_ratio", 0.35)
        )
        snap_tolerance_ratio = float(
            settings.get("snap_tolerance_ratio", 0.04)
        )
        crop_padding_ratio = float(settings.get("crop_padding_ratio", 0.006))
        manual_crops = settings.get("manual_crops", {})

        height, width = image.shape[:2]

        x0_page = int(round(width * left_exclusion))
        x1_page = int(round(width * (1 - right_exclusion)))
        y0_page = int(round(height * header_exclusion))
        y1_page = int(round(height * (1 - footer_exclusion)))

        if x1_page <= x0_page or y1_page <= y0_page:
            raise ValueError(
                f"Invalid crop exclusions for page {page_number}."
            )

        roi = image[y0_page:y1_page, x0_page:x1_page]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        centers, binary, vertical = detect_vertical_separators(
            gray,
            minimum_line_ratio,
            projection_threshold_ratio,
        )

        boundaries, method, warnings = choose_boundaries(
            roi.shape[1],
            expected_columns,
            centers,
            snap_tolerance_ratio,
        )

        print(
            f"Page {page_number} "
            f"detected centers: "
            f"{centers}"
        )

        print(
            f"Page {page_number} "
            f"selected boundaries: "
            f"{boundaries}"
        )

        page_out = output_dir / f"page_{page_number:03d}"
        page_out.mkdir(parents=True, exist_ok=True)

        padding = int(round(roi.shape[1] * crop_padding_ratio))
        intervals = list(zip(boundaries[:-1], boundaries[1:]))

        if reading_order == "right_to_left":
            intervals = list(reversed(intervals))
        elif reading_order != "left_to_right":
            warnings.append(
                f"Unknown reading_order={reading_order}; used left_to_right."
            )

        page_rows = []

        for logical_index, (left, right) in enumerate(intervals, start=1):
            manual_crop = manual_crops.get(str(logical_index))

            if manual_crop:
                requested_x0 = int(manual_crop["x0"])
                requested_y0 = int(manual_crop["y0"])
                requested_x1 = int(manual_crop["x1"])
                requested_y1 = int(manual_crop["y1"])

                crop_left = max(0, requested_x0)
                crop_top = max(0, requested_y0)
                crop_right = min(width, requested_x1)
                crop_bottom = min(height, requested_y1)

                if crop_right <= crop_left or crop_bottom <= crop_top:
                    raise RuntimeError(
                        f"Page {page_number}, column {logical_index}: "
                        f"invalid manual crop {crop_left},{crop_top},"
                        f"{crop_right},{crop_bottom}."
                    )

                crop = image[
                    crop_top:crop_bottom,
                    crop_left:crop_right,
                ]

                actual_x0 = crop_left
                actual_y0 = crop_top
                actual_x1 = crop_right
                actual_y1 = crop_bottom
                detection_method = "manual_override"

            else:
                crop_left = max(0, left + padding)
                crop_right = min(roi.shape[1], right - padding)
                crop_top = 0
                crop_bottom = roi.shape[0]

                if crop_right <= crop_left:
                    raise RuntimeError(
                        f"Page {page_number}, column {logical_index}: "
                        "automatic crop width is invalid."
                    )

                crop = roi[
                    crop_top:crop_bottom,
                    crop_left:crop_right,
                ]

                actual_x0 = x0_page + crop_left
                actual_y0 = y0_page + crop_top
                actual_x1 = x0_page + crop_right
                actual_y1 = y0_page + crop_bottom
                detection_method = method

            original_name = f"col_{logical_index:02d}_original.png"
            processed_name = f"col_{logical_index:02d}_processed.png"

            original_path = page_out / original_name
            processed_path = page_out / processed_name

            write_image(
                original_path,
                crop,
                "original crop",
            )

            crop_gray = cv2.cvtColor(
                crop,
                cv2.COLOR_BGR2GRAY,
            )

            processed = cv2.adaptiveThreshold(
                crop_gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                41,
                15,
            )

            write_image(
                processed_path,
                processed,
                "processed crop",
            )

            manual_warning = (
                [
                    "Manual crop override used; "
                    "route to exception review."
                ]
                if manual_crop
                else []
            )

            row = {
                "source_pdf_page": page_number,
                "column_index": logical_index,
                "x0": actual_x0,
                "y0": actual_y0,
                "x1": actual_x1,
                "y1": actual_y1,
                "reading_order": reading_order,
                "detection_method": detection_method,
                "column_warning": bool(warnings) or bool(manual_crop),
                "warning_notes": " | ".join(
                    warnings + manual_warning
                ),
                "crop_file": str(
                    original_path.relative_to(root)
                ),
            }

            page_rows.append(row)
            overall_manifest.append(row)

            print(
                f"  Column {logical_index}: "
                f"x={row['x0']}-{row['x1']}, "
                f"y={row['y0']}-{row['y1']}, "
                f"method={row['detection_method']}"
            )

        validate_crop_rows(
            page_number,
            page_rows,
            expected_columns,
        )

        page_manifest_path = page_out / "crop_manifest.csv"

        with page_manifest_path.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(page_rows[0].keys()),
            )
            writer.writeheader()
            writer.writerows(page_rows)

        if args.debug:
            boundary_overlay = roi.copy()

            for boundary in boundaries:
                cv2.line(
                    boundary_overlay,
                    (boundary, 0),
                    (boundary, boundary_overlay.shape[0] - 1),
                    (0, 0, 255),
                    3,
                )

            write_image(
                page_out / "debug_boundaries.png",
                boundary_overlay,
                "boundary debug image",
            )

            rectangle_overlay = image.copy()

            for row in page_rows:
                is_manual = (
                    row["detection_method"]
                    == "manual_override"
                )

                color = (
                    (255, 0, 255)
                    if is_manual
                    else (0, 0, 255)
                )

                cv2.rectangle(
                    rectangle_overlay,
                    (int(row["x0"]), int(row["y0"])),
                    (int(row["x1"]), int(row["y1"])),
                    color,
                    3,
                )

                label_y = max(
                    25,
                    int(row["y0"]) + 28,
                )

                cv2.putText(
                    rectangle_overlay,
                    f"Col {row['column_index']}",
                    (int(row["x0"]) + 5, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2,
                    cv2.LINE_AA,
                )

            write_image(
                page_out / "debug_crop_rectangles.png",
                rectangle_overlay,
                "crop rectangle debug image",
            )

            write_image(
                page_out / "debug_binary.png",
                binary,
                "binary debug image",
            )

            write_image(
                page_out / "debug_vertical_lines.png",
                vertical,
                "vertical-line debug image",
            )

        print(
            f"Page {page_number}: {expected_columns} crops, "
            f"method={method}, detected separators={len(centers)}, "
            f"warnings={len(warnings)}"
        )

    overall_path = output_dir / "all_crop_manifest.csv"

    fieldnames = [
        "source_pdf_page",
        "column_index",
        "x0",
        "y0",
        "x1",
        "y1",
        "reading_order",
        "detection_method",
        "column_warning",
        "warning_notes",
        "crop_file",
    ]

    with overall_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(overall_manifest)

    print(f"Combined crop manifest: {overall_path}")
    print(
        "Review debug boundaries and crop rectangles on pilot pages "
        "before processing the full daily range."
    )


if __name__ == "__main__":
    main()
