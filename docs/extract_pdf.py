"""Extract OGC 2026 problem statement text from PDF for analysis."""
import sys
from pathlib import Path
from pypdf import PdfReader

pdf_path = Path(r"C:\claude-develop\OGC2026\docs\problem-statement-v1.0.pdf")
out_path = Path(r"C:\claude-develop\OGC2026\docs\problem-statement-v1.0.txt")

reader = PdfReader(str(pdf_path))
print(f"Page count: {len(reader.pages)}")

with out_path.open("w", encoding="utf-8") as f:
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        f.write(f"\n\n===== PAGE {i} =====\n\n")
        f.write(text)
        f.write("\n")
print(f"Wrote: {out_path} ({out_path.stat().st_size} bytes)")
