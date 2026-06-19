"""Verdict assertions for tablint. Run: pytest -q (samples auto-generated)."""

import os

import pytest

import tablint
from tests import make_samples

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")


@pytest.fixture(scope="module", autouse=True)
def _samples():
    make_samples.main()


def _v(name):
    return tablint.inspect_table(os.path.join(SAMPLES, name), ["all"])


def test_clean_csv():
    r = _v("clean.csv")
    assert r["verdict"] == "clean"
    assert r["recommended_action"] == "ingest_directly"
    assert r["blocking_conditions"] == []
    assert r["warnings"] == []


def test_clean_tsv():
    assert _v("clean.tsv")["verdict"] == "clean"


def test_clean_xlsx():
    r = _v("clean.xlsx")
    assert r["verdict"] == "clean"
    assert r["sheets"][0]["header_row_index"] == 0


def test_header_on_row_four():
    r = _v("header_row4.csv")
    assert "header_not_on_first_row" in r["blocking_conditions"]
    assert r["recommended_action"] == "clean_then_ingest"
    assert r["sheets"][0]["header_row_index"] == 3


def test_numbers_as_text():
    r = _v("numbers_as_text.csv")
    assert "numbers_stored_as_text" in r["warnings"]
    assert any(c["numbers_as_text"] for c in r["columns"])


def test_ragged_and_totals():
    r = _v("ragged_totals.csv")
    assert any(b.startswith("ragged_rows") for b in r["blocking_conditions"])
    assert "totals_row_in_records" in r["warnings"]


def test_dup_and_empty_columns():
    r = _v("dup_empty_cols.csv")
    assert "duplicate_column_names" in r["blocking_conditions"]
    assert "empty_column_names" in r["blocking_conditions"]


def test_multiple_tables_xlsx():
    r = _v("multi_table.xlsx")
    assert "multiple_tables_detected" in r["blocking_conditions"]
    assert r["recommended_action"] == "split_tables_then_ingest"
    assert "hidden_sheets" in r["warnings"]
    assert any(w.startswith("merged_cells") for w in r["warnings"])
    assert any(w.startswith("formula_cells") for w in r["warnings"])


def test_ambiguous_dates():
    r = _v("ambiguous_dates.csv")
    assert "ambiguous_dates" in r["warnings"]


def test_prose_is_not_a_table():
    r = _v("prose.csv")
    assert r["verdict"] == "not_a_table"
    assert r["recommended_action"] == "reject"


def test_contract_shape():
    r = _v("clean.csv")
    for key in (
        "verdict",
        "confidence",
        "recommended_action",
        "blocking_conditions",
        "warnings",
        "sheets",
        "columns",
    ):
        assert key in r
    assert isinstance(r["confidence"], float)
