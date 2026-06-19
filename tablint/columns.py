"""Column level analysis over a list-of-rows representation.

Input is a header list plus data rows (each a list of cell values as strings or
native types). We avoid heavy pandas dtype inference here so behavior is
identical for csv and xlsx. Pure logic, no IO.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, List, Optional, Tuple

from .types import ColumnReport

_INT_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})*$|^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})*|\d+)?(\.\d+)?([eE][+-]?\d+)?$")
_CURRENCY_RE = re.compile(r"^[\$\u20ac\u00a3\u00a5]\s?[+-]?[\d,]+(\.\d+)?$|^[+-]?[\d,]+(\.\d+)?\s?(USD|EUR|GBP)$")
_PCT_RE = re.compile(r"^[+-]?[\d,]+(\.\d+)?\s?%$")
_BOOL_VALUES = {"true", "false", "yes", "no", "y", "n", "t", "f", "0", "1"}

# Date patterns. The ambiguous ones are those where day/month order is unclear.
_DATE_NUMERIC_RE = re.compile(r"^\s*(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})\s*$")
_DATE_ISO_RE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?\s*$")
_DATE_TEXT_RE = re.compile(
    r"^\s*\d{1,2}[ \-]?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ \-,]?\s*\d{2,4}\s*$",
    re.IGNORECASE,
)


def _is_null(v: Any) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s.lower() in {"na", "n/a", "nan", "null", "none", "-"}


def _is_dirty_numeric_text(v: Any) -> bool:
    """True when a value is a number stored as text in a way that breaks naive
    parsing: thousands separators, currency/percent symbols, leading zeros, or
    surrounding whitespace. Plain '30' or '12.50' is clean and does not count,
    because in a CSV every cell is text by nature.
    """
    if not isinstance(v, str):
        return False
    raw = v
    s = v.strip()
    if s == "" or _is_null(s):
        return False
    has_pad = raw != s
    has_sep = "," in s
    has_currency = bool(_CURRENCY_RE.match(s))
    has_pct = bool(_PCT_RE.match(s))
    core = s.lstrip("+-")
    has_leading_zero = (
        len(core) > 1 and core[0] == "0" and core[1].isdigit()
    )
    if not (has_pad or has_sep or has_currency or has_pct or has_leading_zero):
        return False
    # And it must actually be numeric once the noise is stripped.
    cleaned = (
        s.replace(",", "")
        .replace("$", "")
        .replace("\u20ac", "")
        .replace("\u00a3", "")
        .replace("\u00a5", "")
        .replace("%", "")
        .replace("USD", "")
        .replace("EUR", "")
        .replace("GBP", "")
        .strip()
    )
    return bool(_FLOAT_RE.match(cleaned)) and any(c.isdigit() for c in cleaned)


def _classify_scalar(v: Any) -> str:
    """Classify a single cell into a coarse type token."""
    if _is_null(v):
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    s = str(v).strip()
    low = s.lower()

    if _DATE_ISO_RE.match(s) or _DATE_TEXT_RE.match(s) or _DATE_NUMERIC_RE.match(s):
        return "date"
    if _CURRENCY_RE.match(s):
        return "currency"
    if _PCT_RE.match(s):
        return "percent"
    if _INT_RE.match(s):
        return "int"
    if _FLOAT_RE.match(s) and any(c.isdigit() for c in s):
        return "float"
    if low in _BOOL_VALUES:
        return "bool"
    return "text"


def _looks_ambiguous_date(s: str) -> bool:
    m = _DATE_NUMERIC_RE.match(str(s))
    if not m:
        return False
    a, b, c = m.group(1), m.group(2), m.group(3)
    # ISO-like 4 digit lead is unambiguous.
    if len(a) == 4:
        return False
    try:
        ai, bi = int(a), int(b)
    except ValueError:
        return False
    # If both first two parts are <= 12, day/month order is ambiguous.
    return ai <= 12 and bi <= 12


def analyze_columns(
    header: List[str], rows: List[List[Any]], sample_cap: int = 5000
) -> Tuple[List[ColumnReport], List[str]]:
    """Return (column reports, soft issue tokens)."""
    issues: List[str] = []
    n_cols = len(header)
    sampled = rows[:sample_cap]

    # Duplicate and empty name detection.
    name_counts = Counter(h.strip().lower() for h in header)
    seen: dict[str, int] = {}

    reports: List[ColumnReport] = []
    for ci in range(n_cols):
        raw_name = header[ci] if ci < len(header) else ""
        name = (raw_name or "").strip()
        empty_name = name == ""
        norm = name.lower()
        duplicate_name = (not empty_name) and name_counts[norm] > 1

        col_values = [r[ci] if ci < len(r) else None for r in sampled]
        non_null = [v for v in col_values if not _is_null(v)]
        null_pct = (
            100.0 * (len(col_values) - len(non_null)) / len(col_values)
            if col_values
            else 0.0
        )

        type_tokens = [_classify_scalar(v) for v in non_null]
        token_counts = Counter(type_tokens)
        if token_counts:
            dominant, dom_n = token_counts.most_common(1)[0]
            type_consistency = dom_n / len(type_tokens) if type_tokens else 1.0
        else:
            dominant, type_consistency = "unknown", 1.0

        # numbers-as-text: numeric column whose cells are stored as text in a
        # way that breaks parsing (separators, currency, leading zeros, etc).
        dirty_numbers = sum(1 for v in non_null if _is_dirty_numeric_text(v))
        numbers_as_text = (
            dominant in {"int", "float", "currency", "percent"}
            and dirty_numbers > 0
            and dirty_numbers >= 0.3 * max(len(non_null), 1)
        )

        ambiguous_dates = dominant == "date" and any(
            _looks_ambiguous_date(v) for v in non_null if isinstance(v, str)
        )

        reports.append(
            ColumnReport(
                name=name if not empty_name else f"column_{ci + 1}",
                inferred_type=dominant,
                null_pct=null_pct,
                type_consistency=type_consistency,
                numbers_as_text=numbers_as_text,
                ambiguous_dates=ambiguous_dates,
                duplicate_name=duplicate_name,
                empty_name=empty_name,
            )
        )

        if empty_name:
            issues.append(f"empty_column_name:index_{ci + 1}")
        if duplicate_name and norm not in seen:
            issues.append(f"duplicate_column_name:{name}")
            seen[norm] = 1
        if numbers_as_text:
            issues.append(f"numbers_stored_as_text:{reports[-1].name}")
        if ambiguous_dates:
            issues.append(f"ambiguous_dates:{reports[-1].name}")
        if type_consistency < 0.9 and dominant != "unknown" and len(non_null) >= 5:
            issues.append(f"mixed_column_types:{reports[-1].name}")

    return reports, issues


def detect_totals_row(header: List[str], rows: List[List[Any]]) -> bool:
    """Heuristic: a trailing row labeled total/sum/subtotal in any cell."""
    if not rows:
        return False
    for r in rows[-3:]:
        for cell in r:
            if cell is None:
                continue
            s = str(cell).strip().lower()
            if s in {"total", "totals", "sum", "subtotal", "grand total"}:
                return True
    return False


def count_ragged_rows(header: List[str], rows: List[List[Any]]) -> int:
    """Rows whose non-empty width differs from the header width."""
    width = len(header)
    ragged = 0
    for r in rows:
        # trailing-empty tolerance: trim trailing nulls before comparing.
        trimmed = list(r)
        while trimmed and _is_null(trimmed[-1]):
            trimmed.pop()
        if len(trimmed) > width or (0 < len(trimmed) < width and len(trimmed) != width):
            if len(trimmed) != width:
                ragged += 1
    return ragged
