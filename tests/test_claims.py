"""
Test to detect and prevent unsupported promotional claims across documentation and UI templates.
Scans target files for words like 'guarantee', 'zero ', '100% pass', 'seamless', 'robust'.
Ignores CSS (e.g., width: 100%, keyframes), HTML comments, and legacy_team/.
Runs completely offline with no network or LLM calls.
"""

import re
from pathlib import Path

TARGET_FILES = [
    Path("frontend/templates/schedule.html"),
    Path("README.md"),
    Path("docs/api.md"),
    Path("frontend/templates/data_manager.html"),
]

FORBIDDEN_PATTERNS = [
    (r"\bguarantee\w*", "guarantee"),
    (r"\bzero\s+(?!state\b)(?![0-9])", "zero "),
    (r"100%\s*(?:pass|prerequisite)", "100% pass"),
    (r"\bseamless\w*", "seamless"),
    (r"\brobust\w*", "robust"),
]


def _is_css_or_style_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("/*") or stripped.endswith("*/"):
        return True
    if re.search(r"(width|height|max-width|opacity|margin|padding|flex|transform|scale)\s*:\s*[^;]+;", stripped):
        return True
    if re.search(r"\b\d+%\s*\{", stripped):  # Keyframe animation rule (e.g., 100% { ...)
        return True
    if stripped.startswith("<!-- Zero State Banner"):  # Design pattern comment for empty-state UI
        return True
    return False


def test_no_unsupported_claims_in_target_files():
    """Fails if any target file contains unsupported claims."""
    violations = []

    for file_path in TARGET_FILES:
        assert file_path.exists(), f"Target file does not exist: {file_path}"
        text = file_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        for line_no, line in enumerate(lines, 1):
            if _is_css_or_style_line(line):
                continue

            for pattern, phrase in FORBIDDEN_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    violations.append(
                        f"{file_path}:{line_no} contains forbidden claim '{phrase}': '{line.strip()}'"
                    )

    assert not violations, "Found unsupported claims:\n" + "\n".join(violations)


README_FALSE_CLAIMS = [
    (r"\bspeaker\s+simultaneity\b", "speaker simultaneity"),
    (r"POST\s+/reset\b", "POST /reset"),
    (r"\bcommits\s+directly\b", "commits directly"),
]


def test_readme_has_no_false_runtime_claims():
    """Fails if README.md reintroduces known disproven runtime claims."""
    readme = Path("README.md")
    assert readme.exists(), "README.md does not exist"
    violations = []

    for line_no, line in enumerate(readme.read_text(encoding="utf-8").splitlines(), 1):
        for pattern, label in README_FALSE_CLAIMS:
            if re.search(pattern, line, re.IGNORECASE):
                violations.append(
                    f"README.md:{line_no} contains disproven claim '{label}': '{line.strip()}'"
                )

    assert not violations, "Found disproven claims in README.md:\n" + "\n".join(violations)
