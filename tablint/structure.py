"""Generic structure detection over a matrix of rows (list of lists).

Used by both the CSV and XLSX paths. Decides where the header row is, whether
there are multiple table regions stacked on a sheet, and counts repeated header
rows. Pure logic, no IO.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _row_filled(row: List[Any]) -> int:
    return sum(0 if _is_blank(c) else 1 for c in row)


def _row_is_blank(row: List[Any]) -> bool:
    return _row_filled(row) == 0


def _looks_like_header(row: List[Any]) -> float:
    """Score 0..1 that a row is a header: mostly non-blank text, few pure numbers."""
    cells = [c for c in row if not _is_blank(c)]
    if not cells:
        return 0.0
    text_like = 0
    numeric_like = 0
    for c in cells:
        s = str(c).strip()
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            numeric_like += 1
        elif s.replace(",", "").replace(".", "").replace("-", "").isdigit():
            numeric_like += 1
        else:
            text_like += 1
    fill_ratio = len(cells) / max(len(row), 1)
    text_ratio = text_like / len(cells)
    return round(0.6 * text_ratio + 0.4 * fill_ratio, 3)


def detect_header_row(matrix: List[List[Any]], scan_limit: int = 25) -> Optional[int]:
    """Return the 0-based index of the most likely header row, or None.

    A header candidate must (a) look like a header and (b) have a filled width
    close to the table's dominant content width. This prevents single-cell title
    or preamble rows above a wide table from being chosen as the header.
    """
    # Dominant content width: the widest filled row in the scanned region. Title
    # rows are typically much narrower than the real table, so width gates them.
    widths = [_row_filled(r) for r in matrix[: max(scan_limit, 40)] if not _row_is_blank(r)]
    if not widths:
        return None
    dominant_width = max(widths)
    width_floor = max(2, int(0.7 * dominant_width)) if dominant_width >= 2 else 1

    best_idx, best_score = None, 0.0
    for i, row in enumerate(matrix[:scan_limit]):
        if _row_is_blank(row):
            continue
        if _row_filled(row) < width_floor:
            continue
        score = _looks_like_header(row)
        if score >= 0.6 and score > best_score:
            best_idx, best_score = i, score
            if score >= 0.75:
                break
    if best_idx is None:
        # Fall back to the first non-blank row meeting the width floor, else the
        # first non-blank row at all.
        for i, row in enumerate(matrix[:scan_limit]):
            if not _row_is_blank(row) and _row_filled(row) >= width_floor:
                return i
        for i, row in enumerate(matrix[:scan_limit]):
            if not _row_is_blank(row):
                return i
    return best_idx


def detect_multiple_tables(matrix: List[List[Any]]) -> Tuple[bool, int]:
    """Detect stacked table regions separated by one or more blank rows.

    Returns (multiple_detected, region_count). A region is a run of non-blank
    rows. Leading/trailing blanks are ignored. Two or more substantial regions
    separated by blanks signals multiple tables.
    """
    regions: List[Tuple[int, int]] = []
    start = None
    for i, row in enumerate(matrix):
        if _row_is_blank(row):
            if start is not None:
                regions.append((start, i - 1))
                start = None
        else:
            if start is None:
                start = i
    if start is not None:
        regions.append((start, len(matrix) - 1))

    # A real table region needs at least 2 rows and at least 2 columns of
    # content. Single-column title/preamble blocks above a table do not count.
    def _region_width(a: int, b: int) -> int:
        w = 0
        for i in range(a, b + 1):
            w = max(w, _row_filled(matrix[i]))
        return w

    substantial = [
        r
        for r in regions
        if (r[1] - r[0] + 1) >= 2 and _region_width(r[0], r[1]) >= 2
    ]
    return (len(substantial) >= 2, len(substantial))


def count_repeated_header_rows(matrix: List[List[Any]], header_idx: int) -> int:
    """Count rows below the header that duplicate the header values."""
    if header_idx is None or header_idx >= len(matrix):
        return 0
    header = [
        "" if _is_blank(c) else str(c).strip().lower() for c in matrix[header_idx]
    ]
    non_blank_header = [h for h in header if h]
    if not non_blank_header:
        return 0
    count = 0
    for row in matrix[header_idx + 1 :]:
        norm = ["" if _is_blank(c) else str(c).strip().lower() for c in row]
        width = min(len(norm), len(header))
        if width == 0:
            continue
        # Count matches only on positions where the header cell is non-blank.
        matches = sum(
            1 for a, b in zip(header[:width], norm[:width]) if a and a == b
        )
        if matches >= max(2, int(0.8 * len(non_blank_header))):
            count += 1
    return count


def used_range_a1(n_rows: int, n_cols: int) -> Optional[str]:
    """Build an A1-style used range string from dimensions."""
    if n_rows <= 0 or n_cols <= 0:
        return None
    return f"A1:{_col_letter(n_cols)}{n_rows}"


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s
