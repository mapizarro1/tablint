"""Low level detection: real file type by magic bytes, text encoding, delimiter.

Pure functions over a local file path. No network, no payment awareness.
"""

from __future__ import annotations

import csv
import os
from typing import Optional, Tuple

from charset_normalizer import from_bytes

# Magic byte signatures we care about for the MVP (csv, tsv, xlsx).
# xlsx is a zip container, so it starts with PK\x03\x04.
# Legacy .xls (OLE2) starts with D0 CF 11 E0; we detect it only to reject it.
_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def declared_extension(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    return ext or "unknown"


def detect_real_type(file_path: str) -> str:
    """Return one of: xlsx, xls_legacy, text, empty, unknown.

    'text' covers csv/tsv/plain; the delimiter sniff disambiguates later.
    We read a small prefix only.
    """
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return "unknown"
    if size == 0:
        return "empty"

    with open(file_path, "rb") as fh:
        head = fh.read(8)

    if head.startswith(_ZIP_MAGIC):
        # Could be xlsx or another OOXML/zip; confirm with a content peek.
        if _looks_like_xlsx(file_path):
            return "xlsx"
        return "zip_unknown"
    if head.startswith(_OLE2_MAGIC):
        return "xls_legacy"

    # Heuristic: if a sample decodes as text and is mostly printable, call it text.
    with open(file_path, "rb") as fh:
        sample = fh.read(65536)
    if _is_probably_text(sample):
        return "text"
    return "unknown"


def _looks_like_xlsx(file_path: str) -> bool:
    try:
        import zipfile

        with zipfile.ZipFile(file_path) as zf:
            names = set(zf.namelist())
        return "xl/workbook.xml" in names or any(n.startswith("xl/") for n in names)
    except Exception:
        return False


def _is_probably_text(sample: bytes) -> bool:
    if not sample:
        return False
    # A high count of NUL bytes is a strong binary signal.
    if sample.count(b"\x00") > 0:
        return False
    # Count bytes outside the typical printable/whitespace range after decode.
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(sample).best()
        if best is None:
            return False
        text = str(best)
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    return printable / max(len(text), 1) > 0.85


def detect_encoding(file_path: str, max_bytes: int = 200000) -> str:
    """Best effort text encoding via charset-normalizer. Defaults to utf-8."""
    with open(file_path, "rb") as fh:
        sample = fh.read(max_bytes)
    if not sample:
        return "utf-8"
    best = from_bytes(sample).best()
    if best is None or best.encoding is None:
        return "utf-8"
    return best.encoding


def sniff_delimiter(
    file_path: str, encoding: str, declared_ext: str
) -> Tuple[Optional[str], float]:
    """Return (delimiter, confidence in 0..1). None if it cannot be sniffed."""
    with open(file_path, "r", encoding=encoding, errors="replace", newline="") as fh:
        sample = fh.read(65536)
    if not sample.strip():
        return None, 0.0

    candidates = [",", "\t", ";", "|"]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(candidates))
        return dialect.delimiter, 0.9
    except csv.Error:
        pass

    # Fallback: pick the candidate with the most consistent per-line count.
    lines = [ln for ln in sample.splitlines() if ln.strip()][:50]
    if not lines:
        return None, 0.0
    best_delim, best_score = None, -1.0
    for delim in candidates:
        counts = [ln.count(delim) for ln in lines]
        if max(counts) == 0:
            continue
        # Prefer a delimiter whose count is high and consistent.
        consistency = counts.count(max(set(counts), key=counts.count)) / len(counts)
        score = consistency * (1 if max(counts) > 0 else 0)
        if score > best_score:
            best_delim, best_score = delim, score
    if best_delim is None:
        # Single column file. Default to comma but low confidence.
        return ",", 0.2
    return best_delim, round(min(best_score, 0.85), 2)
