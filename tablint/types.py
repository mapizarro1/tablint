"""Result types for tablint.

These mirror the public contract exactly. They are plain dataclasses with a
to_dict() so the gateway can serialize them without importing tablint internals.
No payment, transport, or x402 concepts appear here. This is pure logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional

# Verdict values, ordered from safest to least safe.
VERDICT_CLEAN = "clean"
VERDICT_NEEDS_CLEANING = "needs_cleaning"
VERDICT_NEEDS_REVIEW = "needs_review"
VERDICT_REJECT = "reject"
VERDICT_NOT_A_TABLE = "not_a_table"

# Recommended actions.
ACTION_INGEST_DIRECTLY = "ingest_directly"
ACTION_CLEAN_THEN_INGEST = "clean_then_ingest"
ACTION_SPLIT_TABLES_THEN_INGEST = "split_tables_then_ingest"
ACTION_MAP_MANUALLY = "map_manually"
ACTION_REVIEW = "review"
ACTION_REJECT = "reject"


@dataclass
class SheetReport:
    name: str
    hidden: bool = False
    used_range: Optional[str] = None
    header_row_index: Optional[int] = None
    multiple_tables_detected: bool = False
    merged_cells: int = 0
    repeated_header_rows: int = 0
    ragged_rows: int = 0
    formula_cells: int = 0
    error_cells: int = 0
    external_links: int = 0
    totals_row_detected: bool = False


@dataclass
class ColumnReport:
    name: str
    inferred_type: str = "unknown"
    null_pct: float = 0.0
    type_consistency: float = 1.0
    numbers_as_text: bool = False
    ambiguous_dates: bool = False
    duplicate_name: bool = False
    empty_name: bool = False


@dataclass
class TableResult:
    verdict: str
    confidence: float
    recommended_action: str
    blocking_conditions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sheets: List[SheetReport] = field(default_factory=list)
    columns: List[ColumnReport] = field(default_factory=list)
    # Diagnostics not part of the wire contract but useful in logs.
    detected_type: Optional[str] = None
    declared_type: Optional[str] = None
    encoding: Optional[str] = None
    delimiter: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Round floats for stable output.
        d["confidence"] = round(float(self.confidence), 3)
        for col in d["columns"]:
            col["null_pct"] = round(float(col["null_pct"]), 1)
            col["type_consistency"] = round(float(col["type_consistency"]), 3)
        return d
