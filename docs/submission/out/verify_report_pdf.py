import re
import sys
from pathlib import Path

DOCS_SUBMISSION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS_SUBMISSION))

from build_report import (
    extract_page_text_from_pdf,
    PDF_OUTPUT_PATH,
    BANNED_WORDS,
    extract_allowed_numbers,
    get_pdf_page_count,
)

text = extract_page_text_from_pdf(PDF_OUTPUT_PATH)
print(f"Total extracted characters: {len(text)}")
print(f"Total extracted words: {len(text.split())}")

# Check banned words
banned_matches = {}
for bw in BANNED_WORDS:
    pat = rf"\b{re.escape(bw)}\b" if not bw.endswith("%") else re.escape(bw)
    matches = re.findall(pat, text, re.IGNORECASE)
    if matches:
        banned_matches[bw] = matches
print(f"Banned words matches: {banned_matches}")

# Check leftover bracket tags
bracket_tags = re.findall(r"\[[^\]]*\]", text)
print(f"Leftover bracket tags count: {len(bracket_tags)}")
if bracket_tags:
    print(f"Tags found: {bracket_tags}")

# Check any '[' character
single_open = list(re.finditer(r"\[", text))
print(f"Total '[' occurrences: {len(single_open)}")

# Check numbers
allowed = extract_allowed_numbers()
numbers = set(re.findall(r"\b\d+(?:\.\d+)*\b", text)).union(re.findall(r"\d+", text))
extra = [n for n in sorted(numbers) if n not in allowed]
print(f"Extraneous numbers count: {len(extra)}")
if extra:
    print(f"Extraneous numbers: {extra}")

# Page count and file size
pages = get_pdf_page_count(PDF_OUTPUT_PATH)
size = PDF_OUTPUT_PATH.stat().st_size
size_mb = size / (1024 * 1024)
print(f"Pages: {pages}")
print(f"Size: {size_mb:.2f} MB ({size} bytes)")
