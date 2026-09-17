from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "source" / "976852581-通勝-丙午年2026.pdf"
OUTPUT = ROOT / "rendered-pages"

OUTPUT.mkdir(exist_ok=True)

document = fitz.open(PDF)

zoom = 355 / 72
matrix = fitz.Matrix(zoom, zoom)

for index, page in enumerate(document):
    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    output_file = (
        OUTPUT
        / f"page_{index + 1:03d}.png"
    )

    pixmap.save(output_file)

print(f"Rendered {len(document)} pages")