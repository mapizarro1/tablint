"""Verdict logic: map detected signals to a verdict and recommended action.

This is the product. It encodes the rules from the build brief:

  not parseable / not tabular        -> reject / not_a_table
  multiple tables / repeated headers -> blocking -> split_tables_then_ingest
  header off row 1 / ragged / dup or
    empty column names               -> blocking -> clean_then_ingest
                                        (map_manually if header is ambiguous)
  soft issues only                   -> needs_cleaning or needs_review
  nothing                            -> clean / ingest_directly
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .types import (
    ACTION_CLEAN_THEN_INGEST,
    ACTION_INGEST_DIRECTLY,
    ACTION_MAP_MANUALLY,
    ACTION_REJECT,
    ACTION_REVIEW,
    ACTION_SPLIT_TABLES_THEN_INGEST,
    VERDICT_CLEAN,
    VERDICT_NEEDS_CLEANING,
    VERDICT_NEEDS_REVIEW,
    VERDICT_NOT_A_TABLE,
    VERDICT_REJECT,
)


@dataclass
class Signals:
    parseable: bool = True
    tabular: bool = True
    multiple_tables: bool = False
    repeated_header_rows: int = 0
    header_off_row_one: bool = False
    header_ambiguous: bool = False
    ragged_rows: int = 0
    duplicate_columns: bool = False
    empty_columns: bool = False
    # Soft signals.
    numbers_as_text: bool = False
    ambiguous_dates: bool = False
    merged_cells: int = 0
    totals_row: bool = False
    formula_cells: int = 0
    error_cells: int = 0
    hidden_sheets: bool = False
    external_links: int = 0
    mixed_types: bool = False
    extra_blocking: List[str] = field(default_factory=list)


def decide(sig: Signals) -> tuple[str, str, List[str], List[str], float]:
    blocking: List[str] = list(sig.extra_blocking)
    warnings: List[str] = []

    # Hard failures first.
    if not sig.parseable:
        blocking.append("file_not_parseable")
        return VERDICT_REJECT, ACTION_REJECT, blocking, warnings, 0.95
    if not sig.tabular:
        blocking.append("not_tabular")
        return VERDICT_NOT_A_TABLE, ACTION_REJECT, blocking, warnings, 0.9

    # Blocking structural problems.
    if sig.multiple_tables:
        blocking.append("multiple_tables_detected")
    if sig.repeated_header_rows > 0:
        blocking.append(f"repeated_header_rows:{sig.repeated_header_rows}")

    if sig.multiple_tables or sig.repeated_header_rows > 0:
        # Splitting must happen before any other cleaning.
        _collect_soft_warnings(sig, warnings)
        return (
            VERDICT_NEEDS_REVIEW,
            ACTION_SPLIT_TABLES_THEN_INGEST,
            blocking,
            warnings,
            0.85,
        )

    structural_block = False
    if sig.header_off_row_one:
        blocking.append("header_not_on_first_row")
        structural_block = True
    if sig.ragged_rows > 0:
        blocking.append(f"ragged_rows:{sig.ragged_rows}")
        structural_block = True
    if sig.duplicate_columns:
        blocking.append("duplicate_column_names")
        structural_block = True
    if sig.empty_columns:
        blocking.append("empty_column_names")
        structural_block = True

    if structural_block:
        _collect_soft_warnings(sig, warnings)
        if sig.header_ambiguous:
            return (
                VERDICT_NEEDS_REVIEW,
                ACTION_MAP_MANUALLY,
                blocking,
                warnings,
                0.75,
            )
        return (
            VERDICT_NEEDS_CLEANING,
            ACTION_CLEAN_THEN_INGEST,
            blocking,
            warnings,
            0.8,
        )

    # Only soft issues remain.
    soft = _collect_soft_warnings(sig, warnings)
    if not soft:
        return VERDICT_CLEAN, ACTION_INGEST_DIRECTLY, blocking, warnings, 0.9

    # Distinguish needs_cleaning (mechanical) from needs_review (judgment).
    review_triggers = sig.ambiguous_dates or sig.error_cells > 0 or sig.mixed_types
    if review_triggers:
        return VERDICT_NEEDS_REVIEW, ACTION_REVIEW, blocking, warnings, 0.7
    return VERDICT_NEEDS_CLEANING, ACTION_CLEAN_THEN_INGEST, blocking, warnings, 0.78


def _collect_soft_warnings(sig: Signals, warnings: List[str]) -> bool:
    added = False
    if sig.numbers_as_text:
        warnings.append("numbers_stored_as_text")
        added = True
    if sig.ambiguous_dates:
        warnings.append("ambiguous_dates")
        added = True
    if sig.mixed_types:
        warnings.append("mixed_column_types")
        added = True
    if sig.merged_cells > 0:
        warnings.append(f"merged_cells:{sig.merged_cells}")
        added = True
    if sig.totals_row:
        warnings.append("totals_row_in_records")
        added = True
    if sig.formula_cells > 0:
        warnings.append(f"formula_cells:{sig.formula_cells}")
        added = True
    if sig.error_cells > 0:
        warnings.append(f"error_cells:{sig.error_cells}")
        added = True
    if sig.hidden_sheets:
        warnings.append("hidden_sheets")
        added = True
    if sig.external_links > 0:
        warnings.append(f"external_links:{sig.external_links}")
        added = True
    return added
