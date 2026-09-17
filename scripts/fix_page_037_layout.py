from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path.cwd()

MANIFEST_PATH = (
    ROOT
    / "page-crops"
    / "page_037"
    / "crop_manifest.csv"
)

CONFIG_PATH = (
    ROOT
    / "config"
    / "crop_templates.json"
)


def as_int(value: str) -> int:
    return int(float(value))


with MANIFEST_PATH.open(
    "r",
    encoding="utf-8-sig",
    newline="",
) as handle:
    rows = list(csv.DictReader(handle))

rows.sort(
    key=lambda row: as_int(
        row["column_index"]
    )
)

if len(rows) != 8:
    raise RuntimeError(
        "Expected 8 original Page 37 crops, "
        f"found {len(rows)}."
    )

old1 = rows[0]
old2 = rows[1]
old3 = rows[2]
old4 = rows[3]
old5 = rows[4]
old6 = rows[5]
old7 = rows[6]
old8 = rows[7]

old1_x0 = as_int(old1["x0"])
old1_x1 = as_int(old1["x1"])

old3_x0 = as_int(old3["x0"])
old3_x1 = as_int(old3["x1"])

old8_x0 = as_int(old8["x0"])
old8_x1 = as_int(old8["x1"])

col1_width = old1_x1 - old1_x0
col3_width = old3_x1 - old3_x0
col8_width = old8_x1 - old8_x0

split3 = (
    old3_x0
    + round(
        col3_width * 0.50
    )
)

new_col1_x1 = (
    old1_x1
    - round(
        col1_width * 0.25
    )
)

new_col9_x0 = (
    old8_x0
    + round(
        col8_width * 0.40
    )
)


def copy_crop(
    row: dict[str, str],
) -> dict[str, int]:
    return {
        "x0": as_int(row["x0"]),
        "y0": as_int(row["y0"]),
        "x1": as_int(row["x1"]),
        "y1": as_int(row["y1"]),
    }


manual_crops = {
    "1": {
        "x0": old1_x0,
        "y0": as_int(old1["y0"]),
        "x1": new_col1_x1,
        "y1": as_int(old1["y1"]),
    },
    "2": copy_crop(old2),
    "3": {
        "x0": split3 + 10,
        "y0": as_int(old3["y0"]),
        "x1": old3_x1,
        "y1": as_int(old3["y1"]),
    },
    "4": {
        "x0": old3_x0,
        "y0": as_int(old3["y0"]),
        "x1": split3 - 10,
        "y1": as_int(old3["y1"]),
    },
    "5": copy_crop(old4),
    "6": copy_crop(old5),
    "7": copy_crop(old6),
    "8": copy_crop(old7),
    "9": {
        "x0": new_col9_x0,
        "y0": as_int(old8["y0"]),
        "x1": old8_x1,
        "y1": as_int(old8["y1"]),
    },
}

for column, crop in manual_crops.items():
    for coordinate in (
        "x0",
        "y0",
        "x1",
        "y1",
    ):
        if crop[coordinate] is None:
            raise RuntimeError(
                f"Column {column}: "
                f"{coordinate} is missing."
            )

    if crop["x1"] <= crop["x0"]:
        raise RuntimeError(
            f"Column {column}: "
            "invalid horizontal range."
        )

    if crop["y1"] <= crop["y0"]:
        raise RuntimeError(
            f"Column {column}: "
            "invalid vertical range."
        )

with CONFIG_PATH.open(
    "r",
    encoding="utf-8-sig",
) as handle:
    config = json.load(handle)

config.setdefault(
    "layout_exceptions",
    {},
)

config["layout_exceptions"]["37"] = {
    "column_count": 9,
    "reading_order": "right_to_left",
    "manual_crops": manual_crops,
}

CONFIG_PATH.write_text(
    json.dumps(
        config,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

print("Page 37 configuration updated.")

for column, crop in manual_crops.items():
    print(
        f"Column {column}: "
        f"x={crop['x0']}-{crop['x1']}, "
        f"y={crop['y0']}-{crop['y1']}"
    )