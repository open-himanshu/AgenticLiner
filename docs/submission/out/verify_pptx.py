import re
from pathlib import Path
from pptx import Presentation

pptx_path = Path("docs/submission/out/OPEN_OUTLIERS_AgenticLiner.pptx")
prs = Presentation(str(pptx_path))

slide_count = len(prs.slides)
file_size_bytes = pptx_path.stat().st_size
file_size_mb = file_size_bytes / (1024 * 1024)

print(f"Slide count: {slide_count}")
print(f"File size: {file_size_bytes} bytes ({file_size_mb:.2f} MB)")

targets = [
    "guarantee",
    "zero",
    "100%",
    "robust",
    "seamless",
    "real-time",
    "two-phase",
    "budget",
    "payment",
    "[",
]

all_found = {t: [] for t in targets}

for s_idx, slide in enumerate(prs.slides):
    slide_texts = []
    for shape in slide.shapes:
        if shape.has_text_frame:
            for p in shape.text_frame.paragraphs:
                slide_texts.append(p.text)
        if shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    for p in cell.text_frame.paragraphs:
                        slide_texts.append(p.text)

    notes_text = ""
    if slide.has_notes_slide:
        notes_text = slide.notes_slide.notes_text_frame.text

    combined = "\n".join(slide_texts + [notes_text])

    for t in targets:
        if t == "[":
            if "[" in combined:
                all_found[t].append(f"Slide {s_idx+1}")
        elif t.endswith("%"):
            if t in combined:
                all_found[t].append(f"Slide {s_idx+1}")
        else:
            pattern = rf"\b{re.escape(t)}\w*"
            m = re.findall(pattern, combined, re.IGNORECASE)
            if m:
                all_found[t].append(f"Slide {s_idx+1}: {m}")

print("\nAudit Results Across All Slides and Speaker Notes:")
all_passed = True
for t in targets:
    res = all_found[t]
    status = "CLEAN (None found)" if not res else f"FOUND: {res}"
    if res:
        all_passed = False
    print(f"  - '{t}': {status}")

print(f"\nFinal Verdict: {'ALL CHECKS PASSED PERFECTLY' if all_passed else 'FAILURES DETECTED'}")
