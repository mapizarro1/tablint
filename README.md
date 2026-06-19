# tablint

A pure spreadsheet inspection engine. It answers one question an AI agent has
before ingesting an unfamiliar CSV, TSV, or XLSX: can I safely ingest this, what
is structurally wrong, and what should I do next.

Free parsers return cells. tablint returns judgment: the header is on row 4,
there are two tables stacked on the sheet, a column is numbers stored as text.

## Scope

This package is pure logic. It holds no payment, wallet, x402, Bazaar, HTTP, or
network code. It receives a local file path and returns a structured verdict.
The payment gateway (x402gate) is a separate repo that calls this one through a
thin adapter. tablint never knows the gateway exists.

## Public interface

One function:

```python
from tablint import inspect_table

result = inspect_table("/path/to/file.xlsx", checks=["all"])
```

`checks` is an iterable of check names, or `["all"]` / `None` for everything.
Unknown names are ignored.

## Output

A dict matching this shape:

```json
{
  "verdict": "clean | needs_cleaning | needs_review | reject | not_a_table",
  "confidence": 0.0,
  "recommended_action": "ingest_directly | clean_then_ingest | split_tables_then_ingest | map_manually | review | reject",
  "blocking_conditions": ["..."],
  "warnings": ["..."],
  "sheets": [
    {
      "name": "Sheet1",
      "hidden": false,
      "used_range": "A1:F210",
      "header_row_index": 3,
      "multiple_tables_detected": true,
      "merged_cells": 12
    }
  ],
  "columns": [
    {
      "name": "Amount",
      "inferred_type": "currency",
      "null_pct": 4.1,
      "type_consistency": 0.92,
      "numbers_as_text": true
    }
  ]
}
```

## Checks

Real file type (magic bytes vs extension), encoding, delimiter sniff, sheet
inventory and hidden sheets, header-row detection, multiple table regions,
repeated header rows, ragged rows, empty or duplicate column names, mixed column
types, numbers stored as text, ambiguous dates, totals row mixed into records,
merged cells, formula and error cells, external links.

## Verdict logic

- not parseable or not tabular -> reject / not_a_table
- multiple tables or repeated headers -> split_tables_then_ingest
- header off row 1, ragged rows, duplicate or empty column names ->
  clean_then_ingest (map_manually if the header is ambiguous)
- soft issues only -> needs_cleaning or needs_review
- nothing -> clean / ingest_directly

## Install

Public package, installable as a git dependency without auth:

```
pip install "tablint @ git+https://github.com/YOUR-USERNAME/tablint.git"
```

Local dev:

```
pip install -e ".[dev]"   # add --break-system-packages in the Claude sandbox
pytest -q
```

## Caps

The engine applies defensive caps (rows, columns, sheets). The gateway enforces
its own pre-payment caps for size and sheet count before any heavy work.
