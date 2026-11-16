"""The sample CSV is large and contains the planted defects."""

from app.services.cleaning import clean_orders
from scripts.generate_orders_csv import BAD_DATE_ROWS, DUPLICATE_ROWS, EMPTY_AMOUNT_ROWS, GOOD_ROWS, build_csv


def test_sample_has_one_thousand_rows_and_each_defect_class() -> None:
    """The generated file is deterministic and the cleaner counts the planted defects."""
    text = build_csv()
    data_rows = [line for line in text.splitlines() if line and not line.startswith("fecha,")]
    assert len(data_rows) >= 1000
    assert len(data_rows) == GOOD_ROWS + DUPLICATE_ROWS + BAD_DATE_ROWS + EMPTY_AMOUNT_ROWS
    assert "13/03/2024" in text
    result = clean_orders(text)
    assert result.duplicate_rows == DUPLICATE_ROWS
    assert result.by_reason()["invalid_date"] == BAD_DATE_ROWS
    assert result.by_reason()["empty_amount"] == EMPTY_AMOUNT_ROWS
    assert result.accepted_rows == GOOD_ROWS
