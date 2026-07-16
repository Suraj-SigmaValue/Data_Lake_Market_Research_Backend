"""
scraper/text_cleaner.py — Post-processing for raw scraped text.

All scrapers pipe their raw output through clean_text() before returning.
Guarantees:
  - No HTML tags
  - No excessive whitespace
  - Deduplicated lines
  - UTF-8 NFKC normalised
  - Printable characters only
"""

from __future__ import annotations

import re
import unicodedata


def clean_text(raw: str) -> str:
    """
    Clean, deduplicate, and normalise raw scraped text.

    Steps:
      1. Unicode NFKC normalisation (fixes fancy quotes, ligatures, etc.)
      2. Strip residual HTML tags (safety net)
      3. Collapse all whitespace runs to a single space
      4. Split into lines, strip each line
      5. Remove blank or single-character lines
      6. Deduplicate identical consecutive lines (common in portal footers)
      7. Rejoin and strip

    Returns UTF-8-safe, printable text.
    """
    if not raw:
        return ""

    # 1. Unicode normalisation
    text = unicodedata.normalize("NFKC", raw)

    # 2. Strip any residual HTML tags (safety net — scrapers should not return HTML)
    text = re.sub(r"<[^>]+>", " ", text)

    # 3. Replace non-printable control chars (except newline/tab) with space
    text = re.sub(r"[^\S\n\t]", " ", text)  # keep newlines and tabs
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)

    # 4. Collapse multiple spaces / tabs on a single line
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 5. Split into lines and clean each
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    seen: set[str] = set()

    for line in lines:
        stripped = line.strip()
        # Skip blank or trivially short lines
        if len(stripped) < 2:
            continue
        # Deduplicate — skip exact duplicate lines (e.g. repeated nav text)
        if stripped in seen:
            continue
        seen.add(stripped)
        cleaned_lines.append(stripped)

    return "\n".join(cleaned_lines).strip()
