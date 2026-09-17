from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ZODIACS = "鼠牛虎兔龍蛇馬羊猴雞狗豬"
DIRECTIONS_8 = ["正北", "東北", "正東", "東南", "正南", "西南", "正西", "西北"]
DIRECTIONS_4 = ["北", "東", "南", "西"]
LUNAR_MONTHS = "正二三四五六七八九十冬臘腊十一十二"
LUNAR_DAYS = [
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
]
VALID_PILLARS = {
    STEMS[index % 10] + BRANCHES[index % 12]
    for index in range(60)
}

LUNAR_DAY_PATTERN = re.compile("|".join(sorted(LUNAR_DAYS, key=len, reverse=True)))
LUNAR_FULL_PATTERN = re.compile(
    r"(?:(正|二|三|四|五|六|七|八|九|十|十一|十二|冬|臘|腊)月)?"
    r"(初一|初二|初三|初四|初五|初六|初七|初八|初九|初十|"
    r"十一|十二|十三|十四|十五|十六|十七|十八|十九|二十|"
    r"廿一|廿二|廿三|廿四|廿五|廿六|廿七|廿八|廿九|三十)"
)
PILLAR_PATTERN = re.compile(rf"[{STEMS}][{BRANCHES}]")
WEALTH_PATTERN = re.compile(r"財神(?:方位)?[：:]?\s*(正?[東西南北]|東北|東南|西北|西南)(?:方)?")
JOY_PATTERN = re.compile(r"喜神(?:方位)?[：:]?\s*(正?[東西南北]|東北|東南|西北|西南)(?:方)?")
CLASH_PATTERN = re.compile(rf"(?:相?沖|冲)\s*([{ZODIACS}])")
SHA_PATTERN = re.compile(r"煞(?:方)?[：:]?\s*(正?[東西南北]|東北|東南|西北|西南)(?:方)?")
COMBINED_CLASH_SHA_PATTERN = re.compile(rf"(?:相?沖|冲)\s*([{ZODIACS}])\s*煞\s*(正?[東西南北]|東北|東南|西北|西南)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build field candidates from PDF-coordinate text and multiple crop OCR passes."
    )
    parser.add_argument("--crop-manifest", default="page-crops/all_crop_manifest.csv")
    parser.add_argument("--coordinate-dir", default="coordinate-text")
    parser.add_argument("--ocr-dir", default="ocr-results")
    parser.add_argument("--output-dir", default="extraction/candidates")
    parser.add_argument("--combined-jsonl", default="extraction/yongjingtang_2026_candidates.jsonl")
    parser.add_argument("--summary-csv", default="extraction/yongjingtang_2026_candidate_summary.csv")
    parser.add_argument("--date-map", default="config/date_column_map.csv")
    parser.add_argument("--pages", default="", help="Optional comma-separated PDF pages.")
    parser.add_argument("--psm", default="4,6,11")
    parser.add_argument("--image-kinds", default="original,processed")
    parser.add_argument("--minimum-token-confidence", type=float, default=0.0)
    return parser.parse_args()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def normalize_text(text: str) -> str:
    return (
        str(text or "")
        .replace(" ", "")
        .replace("\u3000", "")
        .replace("\n", "")
        .replace("冲", "沖")
        .replace("财", "財")
        .replace("喜神方", "喜神")
        .replace("财神", "財神")
    )


def normalize_direction(value: str, sha: bool = False) -> str:
    value = str(value or "").strip().replace("方", "")
    aliases = {
        "北": "北" if sha else "正北",
        "東": "東" if sha else "正東",
        "南": "南" if sha else "正南",
        "西": "西" if sha else "正西",
        "正北": "北" if sha else "正北",
        "正東": "東" if sha else "正東",
        "正南": "南" if sha else "正南",
        "正西": "西" if sha else "正西",
        "東北": "東北",
        "東南": "東南",
        "西北": "西北",
        "西南": "西南",
    }
    return aliases.get(value, "")


def unique(values: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def load_crop_manifest(path: Path, requested_pages: set[int]) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Crop manifest not found: {path}")
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            page = as_int(row.get("source_pdf_page"))
            column = as_int(row.get("column_index"))
            if not page or not column:
                continue
            if requested_pages and page not in requested_pages:
                continue
            rows.append(row)
    return sorted(rows, key=lambda x: (as_int(x["source_pdf_page"]), as_int(x["column_index"])))


def load_date_map(path: Path) -> dict[tuple[int, int], dict[str, str]]:
    if not path.exists():
        return {}
    result = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (as_int(row.get("source_pdf_page")), as_int(row.get("column_index")))
            if key[0] and key[1]:
                result[key] = row
    return result


def coordinate_file(directory: Path, page: int) -> Path | None:
    candidates = [
        directory / f"page_{page:03d}_words.csv",
        directory / f"page_{page:03d}.csv",
        directory / f"page_{page}_words.csv",
    ]
    return next((path for path in candidates if path.exists()), None)


def load_coordinate_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def coordinate_text_in_crop(rows: list[dict[str, str]], crop: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    cx0, cy0 = as_float(crop.get("x0")), as_float(crop.get("y0"))
    cx1, cy1 = as_float(crop.get("x1")), as_float(crop.get("y1"))
    if None in {cx0, cy0, cx1, cy1}:
        return "", []

    selected = []
    for row in rows:
        x0 = as_float(row.get("x0"))
        y0 = as_float(row.get("y0") or row.get("top"))
        x1 = as_float(row.get("x1"))
        y1 = as_float(row.get("y1") or row.get("bottom"))
        if None in {x0, y0, x1, y1}:
            continue
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2
        if cx0 <= center_x <= cx1 and cy0 <= center_y <= cy1:
            selected.append({
                "text": row.get("text", ""),
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            })

    # Chinese vertical text usually reads top-to-bottom, with columns right-to-left.
    selected.sort(key=lambda item: (-item["x0"], item["y0"]))
    return "\n".join(item["text"] for item in selected if item["text"]), selected


def ocr_files(ocr_dir: Path, page: int, column: int, kinds: list[str], psms: list[int]) -> list[Path]:
    result = []
    for kind in kinds:
        for psm in psms:
            path = ocr_dir / f"page_{page:03d}_col_{column:02d}_{kind}_psm{psm}.json"
            if path.exists():
                result.append(path)
    return result


def load_ocr_sources(paths: list[Path], minimum_confidence: float) -> list[dict[str, Any]]:
    sources = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tokens = payload.get("tokens", [])
        eligible = []
        for token in tokens:
            confidence = as_float(token.get("confidence"))
            text = str(token.get("text", "")).strip()
            if text and confidence is not None and confidence >= minimum_confidence:
                eligible.append(text)
        text = "\n".join(eligible) if eligible else str(payload.get("text", ""))
        sources.append({
            "source": path.stem,
            "kind": payload.get("image_kind"),
            "psm": payload.get("psm"),
            "text": text,
            "mean_confidence": payload.get("mean_confidence"),
            "median_confidence": payload.get("median_confidence"),
            "json_file": str(path),
        })
    return sources


def extract_lunar_dates(text: str, month_hint: str = "") -> list[str]:
    cleaned = normalize_text(text)
    values = []
    for month, day in LUNAR_FULL_PATTERN.findall(cleaned):
        if month:
            values.append(f"{month}月{day}")
        elif month_hint:
            values.append(f"{month_hint}{day}" if month_hint.endswith("月") else f"{month_hint}月{day}")
        else:
            values.append(day)
    return unique(values)


def extract_pillars(text: str) -> list[str]:
    return unique(value for value in PILLAR_PATTERN.findall(normalize_text(text)) if value in VALID_PILLARS)


def extract_directions(text: str, label: str) -> list[str]:
    cleaned = normalize_text(text)
    pattern = WEALTH_PATTERN if label == "wealth" else JOY_PATTERN
    values = [normalize_direction(value) for value in pattern.findall(cleaned)]
    return unique(value for value in values if value in DIRECTIONS_8)


def extract_clash_sha(text: str) -> tuple[list[str], list[str]]:
    cleaned = normalize_text(text)
    clash = []
    sha = []
    for zodiac, direction in COMBINED_CLASH_SHA_PATTERN.findall(cleaned):
        clash.append(zodiac)
        normalized = normalize_direction(direction, sha=True)
        if normalized:
            sha.append(normalized)
    clash.extend(CLASH_PATTERN.findall(cleaned))
    sha.extend(normalize_direction(value, sha=True) for value in SHA_PATTERN.findall(cleaned))
    return unique(value for value in clash if value in ZODIACS), unique(value for value in sha if value)


def source_candidates(source_name: str, text: str, month_hint: str = "") -> dict[str, Any]:
    clash, sha = extract_clash_sha(text)
    return {
        "source": source_name,
        "text": text,
        "lunar_date_candidates": extract_lunar_dates(text, month_hint),
        "day_pillar_candidates": extract_pillars(text),
        "wealth_direction_candidates": extract_directions(text, "wealth"),
        "joy_direction_candidates": extract_directions(text, "joy"),
        "clash_zodiac_candidates": clash,
        "sha_direction_candidates": sha,
    }


def consensus(values_by_source: list[list[str]]) -> dict[str, Any]:
    votes = Counter(value for values in values_by_source for value in set(values))
    ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
    return {
        "candidates": [value for value, _ in ranked],
        "vote_counts": dict(ranked),
        "top_candidate": ranked[0][0] if ranked else None,
        "top_votes": ranked[0][1] if ranked else 0,
        "source_count": len(values_by_source),
    }


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    crop_manifest = resolve(root, args.crop_manifest)
    coordinate_dir = resolve(root, args.coordinate_dir)
    ocr_dir = resolve(root, args.ocr_dir)
    output_dir = resolve(root, args.output_dir)
    combined_jsonl = resolve(root, args.combined_jsonl)
    summary_csv = resolve(root, args.summary_csv)
    date_map_path = resolve(root, args.date_map)
    output_dir.mkdir(parents=True, exist_ok=True)
    combined_jsonl.parent.mkdir(parents=True, exist_ok=True)
    summary_csv.parent.mkdir(parents=True, exist_ok=True)

    requested_pages = {as_int(x) for x in args.pages.split(",") if x.strip()}
    psms = [as_int(x) for x in args.psm.split(",") if x.strip()]
    kinds = [x.strip() for x in args.image_kinds.split(",") if x.strip()]
    crops = load_crop_manifest(crop_manifest, requested_pages)
    date_map = load_date_map(date_map_path)

    coordinate_cache: dict[int, list[dict[str, str]]] = {}
    records = []
    summary_rows = []

    for crop in crops:
        page = as_int(crop["source_pdf_page"])
        column = as_int(crop["column_index"])
        key = (page, column)
        mapping = date_map.get(key, {})
        month_hint = mapping.get("lunar_month", "")

        if page not in coordinate_cache:
            coordinate_cache[page] = load_coordinate_rows(coordinate_file(coordinate_dir, page))
        pdf_text, pdf_tokens = coordinate_text_in_crop(coordinate_cache[page], crop)

        ocr_sources = load_ocr_sources(
            ocr_files(ocr_dir, page, column, kinds, psms),
            args.minimum_token_confidence,
        )

        extracted_sources = []
        if pdf_text:
            extracted_sources.append(source_candidates("pdf_coordinates", pdf_text, month_hint))
        for source in ocr_sources:
            parsed = source_candidates(source["source"], source["text"], month_hint)
            parsed["mean_confidence"] = source["mean_confidence"]
            parsed["median_confidence"] = source["median_confidence"]
            parsed["json_file"] = source["json_file"]
            extracted_sources.append(parsed)

        field_names = [
            "lunar_date_candidates",
            "day_pillar_candidates",
            "wealth_direction_candidates",
            "joy_direction_candidates",
            "clash_zodiac_candidates",
            "sha_direction_candidates",
        ]
        agreements = {
            name: consensus([source[name] for source in extracted_sources])
            for name in field_names
        }

        original_crop = crop.get("crop_file", "")
        record = {
            "date_candidate": mapping.get("date", "") or None,
            "date_mapping_source": mapping.get("mapping_source", "") or None,
            "lunar_month_hint": month_hint or None,
            "lunar_date_candidates": agreements["lunar_date_candidates"]["candidates"],
            "day_pillar_candidates": agreements["day_pillar_candidates"]["candidates"],
            "wealth_direction_candidates": agreements["wealth_direction_candidates"]["candidates"],
            "joy_direction_candidates": agreements["joy_direction_candidates"]["candidates"],
            "clash_zodiac_candidates": agreements["clash_zodiac_candidates"]["candidates"],
            "sha_direction_candidates": agreements["sha_direction_candidates"]["candidates"],
            "field_agreement": agreements,
            "source_pdf_page": page,
            "column_index": column,
            "source_crop": original_crop,
            "crop_coordinates": {
                "x0": as_int(crop.get("x0")),
                "y0": as_int(crop.get("y0")),
                "x1": as_int(crop.get("x1")),
                "y1": as_int(crop.get("y1")),
            },
            "column_warning": truthy(crop.get("column_warning")),
            "column_warning_notes": crop.get("warning_notes", ""),
            "pdf_coordinate_text": pdf_text,
            "pdf_coordinate_tokens": pdf_tokens,
            "extraction_sources": extracted_sources,
            "ocr_pass_count": len(ocr_sources),
            "candidate_build_status": (
                "needs_date_mapping" if not mapping.get("date")
                else "no_text_sources" if not extracted_sources
                else "candidate_created"
            ),
        }

        output_path = output_dir / f"page_{page:03d}_col_{column:02d}_candidate.json"
        output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)

        summary_rows.append({
            "date_candidate": record["date_candidate"] or "",
            "source_pdf_page": page,
            "column_index": column,
            "source_crop": original_crop,
            "day_pillar_top": agreements["day_pillar_candidates"]["top_candidate"] or "",
            "day_pillar_votes": agreements["day_pillar_candidates"]["top_votes"],
            "lunar_date_top": agreements["lunar_date_candidates"]["top_candidate"] or "",
            "wealth_direction_top": agreements["wealth_direction_candidates"]["top_candidate"] or "",
            "joy_direction_top": agreements["joy_direction_candidates"]["top_candidate"] or "",
            "clash_zodiac_top": agreements["clash_zodiac_candidates"]["top_candidate"] or "",
            "sha_direction_top": agreements["sha_direction_candidates"]["top_candidate"] or "",
            "ocr_pass_count": len(ocr_sources),
            "column_warning": record["column_warning"],
            "candidate_build_status": record["candidate_build_status"],
            "candidate_json": str(output_path.relative_to(root)),
        })

        print(
            f"Page {page}, column {column}: {record['candidate_build_status']}, "
            f"pillar={summary_rows[-1]['day_pillar_top'] or '--'}, "
            f"OCR passes={len(ocr_sources)}"
        )

    with combined_jsonl.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary_fields = [
        "date_candidate", "source_pdf_page", "column_index", "source_crop",
        "day_pillar_top", "day_pillar_votes", "lunar_date_top",
        "wealth_direction_top", "joy_direction_top", "clash_zodiac_top",
        "sha_direction_top", "ocr_pass_count", "column_warning",
        "candidate_build_status", "candidate_json",
    ]
    with summary_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    if not date_map_path.exists():
        date_map_path.parent.mkdir(parents=True, exist_ok=True)
        with date_map_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["source_pdf_page", "column_index", "date", "lunar_month", "mapping_source", "notes"],
            )
            writer.writeheader()
            for crop in crops:
                writer.writerow({
                    "source_pdf_page": crop["source_pdf_page"],
                    "column_index": crop["column_index"],
                    "date": "",
                    "lunar_month": "",
                    "mapping_source": "",
                    "notes": "Populate before date-based validation.",
                })
        print(f"Starter date map created: {date_map_path}")

    print(f"Candidate JSON directory: {output_dir}")
    print(f"Combined JSONL: {combined_jsonl}")
    print(f"Summary CSV: {summary_csv}")
    print(f"Candidate records: {len(records)}")


if __name__ == "__main__":
    main()
