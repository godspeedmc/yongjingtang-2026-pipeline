from pathlib import Path
import csv
import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "source" / "976852581-通勝-丙午年2026.pdf"
OUTPUT = ROOT / "coordinate-text"

OUTPUT.mkdir(exist_ok=True)

document = fitz.open(PDF)

for page_index, page in enumerate(document):
    words = page.get_text("words")

    output_file = (
        OUTPUT
        / f"page_{page_index + 1:03d}_words.csv"
    )

    with output_file.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        writer = csv.writer(file)

        writer.writerow([
            "x0",
            "y0",
            "x1",
            "y1",
            "text",
            "block",
            "line",
            "word"
        ])

        for word in words:
            writer.writerow(word)

print("Coordinate extraction completed")