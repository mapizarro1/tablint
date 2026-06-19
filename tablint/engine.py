"""tablint engine: the single public entry point inspect_table(file_path, checks).

Routes by detected file type, runs the requested checks, aggregates signals, and
returns a TableResult. No network. No payment awareness. A local file path in,
a structured verdict out.
"""

from __future__ import annotations

import csv as _csv
from typing import Any, Iterable, List, Optional

from . import columns as col_mod
from . import detect as det
from . import sheets as sheet_mod
from . import structure as struct
from .types import ColumnReport, SheetReport, TableResult
from .verdict import Signals, decide

ALL_CHECKS = "all"

# Caps. The gateway enforces its own pre-payment caps; these are a defensive
# backstop inside the engine.
MAX_ROWS = 5000
MAX_COLS = 200
MAX_SHEETS = 20


def inspect_table(file_path: str, checks: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Inspect a local CSV/TSV/XLSX file and return a verdict dict.

    checks: iterable of check names, or ["all"] / None for everything. Unknown
    check names are ignored. The return value matches the public contract.
    """
    wanted = _normalize_checks(checks)

    declared = det.declared_extension(file_path)
    real_type = det.detect_real_type(file_path)

    if real_type == "empty":
        return _fail(
            declared, real_type, ["empty_file"], parseable=False
        )
    if real_type == "xls_legacy":
        return _fail(
            declared, real_type, ["legacy_xls_not_supported"], parseable=False
        )
    if real_type in {"unknown", "zip_unknown"}:
        return _fail(
            declared, real_type, ["unrecognized_file_type"], parseable=False
        )

    if real_type == "xlsx":
        return _inspect_xlsx(file_path, declared, wanted)
    return _inspect_text(file_path, declared, wanted)


# --- routing helpers -------------------------------------------------------


def _inspect_text(file_path: str, declared: str, wanted: set[str]) -> dict[str, Any]:
    encoding = det.detect_encoding(file_path)
    delimiter, _conf = det.sniff_delimiter(file_path, encoding, declared)
    if delimiter is None:
        delimiter = "\t" if declared == "tsv" else ","

    matrix = _read_csv_matrix(file_path, encoding, delimiter)
    if not matrix:
        res = _fail(declared, "text", ["no_rows"], parseable=False)
        res["encoding"] = encoding
        res["delimiter"] = delimiter
        return res

    # A single column of sentence-like free text is not a table.
    if _looks_like_prose(matrix):
        res = _fail(declared, "text", ["single_column_free_text"], parseable=True)
        res["encoding"] = encoding
        res["delimiter"] = delimiter
        return res

    sig, sheet_report, col_reports = _analyze_matrix(
        sheet_name="Sheet1",
        matrix=matrix,
        hidden=False,
        merged=0,
        formula_cells=0,
        error_cells=0,
        external_links=0,
        wanted=wanted,
    )

    verdict, action, blocking, warnings, conf = decide(sig)
    res = TableResult(
        verdict=verdict,
        confidence=conf,
        recommended_action=action,
        blocking_conditions=blocking,
        warnings=warnings,
        sheets=[sheet_report],
        columns=col_reports,
        detected_type="text",
        declared_type=declared,
        encoding=encoding,
        delimiter=delimiter,
    )
    return res.to_dict()


def _inspect_xlsx(file_path: str, declared: str, wanted: set[str]) -> dict[str, Any]:
    sheets = sheet_mod.load_xlsx(
        file_path, max_sheets=MAX_SHEETS, max_rows=MAX_ROWS, max_cols=MAX_COLS
    )
    if not sheets:
        return _fail(declared, "xlsx", ["no_sheets"], parseable=False)

    sheet_reports: List[SheetReport] = []
    all_columns: List[ColumnReport] = []
    agg = Signals()
    agg.parseable = True
    agg.tabular = True

    # Pick the first visible non-empty sheet as the primary table for column
    # reporting; aggregate structural signals across all sheets.
    primary_done = False
    for sd in sheets:
        if not sd.matrix:
            continue
        sig, sheet_report, col_reports = _analyze_matrix(
            sheet_name=sd.name,
            matrix=sd.matrix,
            hidden=sd.hidden,
            merged=sd.merged_cells,
            formula_cells=sd.formula_cells,
            error_cells=sd.error_cells,
            external_links=sd.external_links,
            wanted=wanted,
        )
        sheet_reports.append(sheet_report)

        # OR-merge structural and soft signals across sheets.
        agg.multiple_tables = agg.multiple_tables or sig.multiple_tables
        agg.repeated_header_rows = max(agg.repeated_header_rows, sig.repeated_header_rows)
        agg.header_off_row_one = agg.header_off_row_one or sig.header_off_row_one
        agg.header_ambiguous = agg.header_ambiguous or sig.header_ambiguous
        agg.ragged_rows += sig.ragged_rows
        agg.duplicate_columns = agg.duplicate_columns or sig.duplicate_columns
        agg.empty_columns = agg.empty_columns or sig.empty_columns
        agg.numbers_as_text = agg.numbers_as_text or sig.numbers_as_text
        agg.ambiguous_dates = agg.ambiguous_dates or sig.ambiguous_dates
        agg.merged_cells += sig.merged_cells
        agg.totals_row = agg.totals_row or sig.totals_row
        agg.formula_cells += sig.formula_cells
        agg.error_cells += sig.error_cells
        agg.external_links = max(agg.external_links, sig.external_links)
        agg.mixed_types = agg.mixed_types or sig.mixed_types
        agg.hidden_sheets = agg.hidden_sheets or sd.hidden

        if not primary_done and not sd.hidden:
            all_columns = col_reports
            primary_done = True

    if not sheet_reports:
        return _fail(declared, "xlsx", ["all_sheets_empty"], parseable=False)
    if not all_columns and sheet_reports:
        # Every sheet hidden; still report the first one's columns.
        all_columns = []

    verdict, action, blocking, warnings, conf = decide(agg)
    res = TableResult(
        verdict=verdict,
        confidence=conf,
        recommended_action=action,
        blocking_conditions=blocking,
        warnings=warnings,
        sheets=sheet_reports,
        columns=all_columns,
        detected_type="xlsx",
        declared_type=declared,
    )
    return res.to_dict()


# --- shared matrix analysis ------------------------------------------------


def _analyze_matrix(
    sheet_name: str,
    matrix: List[List[Any]],
    hidden: bool,
    merged: int,
    formula_cells: int,
    error_cells: int,
    external_links: int,
    wanted: set[str],
):
    n_rows = len(matrix)
    n_cols = max((len(r) for r in matrix), default=0)

    header_idx = struct.detect_header_row(matrix) if _on("header_row", wanted) else 0
    if header_idx is None:
        header_idx = 0

    multiple, _regions = (
        struct.detect_multiple_tables(matrix)
        if _on("multiple_tables", wanted)
        else (False, 1)
    )
    repeated = (
        struct.count_repeated_header_rows(matrix, header_idx)
        if _on("repeated_headers", wanted)
        else 0
    )

    header = [(_s(c)) for c in matrix[header_idx]] if header_idx < len(matrix) else []
    data_rows = matrix[header_idx + 1 :]

    ragged = (
        col_mod.count_ragged_rows(header, data_rows) if _on("ragged_rows", wanted) else 0
    )
    col_reports, soft_issues = col_mod.analyze_columns(header, data_rows)
    totals = (
        col_mod.detect_totals_row(header, data_rows) if _on("totals_row", wanted) else False
    )

    dup = any(c.duplicate_name for c in col_reports)
    empty = any(c.empty_name for c in col_reports)
    numbers_as_text = any(c.numbers_as_text for c in col_reports)
    ambiguous_dates = any(c.ambiguous_dates for c in col_reports)
    mixed = any(i.startswith("mixed_column_types") for i in soft_issues)

    # Header ambiguity: header is off row 1 AND the chosen header row scores low.
    header_off = header_idx > 0
    header_ambiguous = header_off and not header

    sig = Signals(
        parseable=True,
        tabular=n_cols >= 1 and n_rows >= 1,
        multiple_tables=multiple,
        repeated_header_rows=repeated,
        header_off_row_one=header_off,
        header_ambiguous=header_ambiguous,
        ragged_rows=ragged,
        duplicate_columns=dup,
        empty_columns=empty,
        numbers_as_text=numbers_as_text,
        ambiguous_dates=ambiguous_dates,
        merged_cells=merged if _on("merged_cells", wanted) else 0,
        totals_row=totals,
        formula_cells=formula_cells if _on("formulas", wanted) else 0,
        error_cells=error_cells if _on("formulas", wanted) else 0,
        hidden_sheets=hidden,
        external_links=external_links if _on("external_links", wanted) else 0,
        mixed_types=mixed,
    )

    sheet_report = SheetReport(
        name=sheet_name,
        hidden=hidden,
        used_range=struct.used_range_a1(n_rows, n_cols),
        header_row_index=header_idx,
        multiple_tables_detected=multiple,
        merged_cells=merged,
        repeated_header_rows=repeated,
        ragged_rows=ragged,
        formula_cells=formula_cells,
        error_cells=error_cells,
        external_links=external_links,
        totals_row_detected=totals,
    )
    return sig, sheet_report, col_reports


# --- small utilities -------------------------------------------------------


def _read_csv_matrix(file_path: str, encoding: str, delimiter: str) -> List[List[Any]]:
    rows: List[List[Any]] = []
    with open(file_path, "r", encoding=encoding, errors="replace", newline="") as fh:
        reader = _csv.reader(fh, delimiter=delimiter)
        for i, row in enumerate(reader):
            if i >= MAX_ROWS:
                break
            rows.append(list(row[:MAX_COLS]))
    return rows


def _looks_like_prose(matrix: List[List[Any]]) -> bool:
    """True when the content is a single column of sentence-like free text."""
    width = max((len(r) for r in matrix), default=0)
    if width > 1:
        return False
    cells = [str(r[0]).strip() for r in matrix if r and str(r[0]).strip()]
    if not cells:
        return False
    sentence_like = sum(
        1 for c in cells if len(c) > 40 or len(c.split()) > 4
    )
    return sentence_like / len(cells) >= 0.6


def _normalize_checks(checks: Optional[Iterable[str]]) -> set[str]:
    if checks is None:
        return {ALL_CHECKS}
    s = {str(c).strip().lower() for c in checks}
    return s or {ALL_CHECKS}


def _on(name: str, wanted: set[str]) -> bool:
    return ALL_CHECKS in wanted or name in wanted


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _fail(
    declared: str, detected: str, conditions: List[str], parseable: bool
) -> dict[str, Any]:
    sig = Signals(parseable=parseable, tabular=False, extra_blocking=conditions)
    verdict, action, blocking, warnings, conf = decide(sig)
    res = TableResult(
        verdict=verdict,
        confidence=conf,
        recommended_action=action,
        blocking_conditions=blocking,
        warnings=warnings,
        sheets=[],
        columns=[],
        detected_type=detected,
        declared_type=declared,
    )
    return res.to_dict()
