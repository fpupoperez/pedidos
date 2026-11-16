"""CSV cleaning rules."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.services.cleaning import CleanError, clean_orders


def test_keeps_the_first_duplicate_and_rejects_bad_rows() -> None:
    """Duplicates, bad dates, empty amounts, and unknown countries are counted."""
    text = "\n".join(
        [
            "fecha,cliente,pais,producto,importe,estado",
            "2024-03-13,Ana Ruiz,España,Teclado,10.50,pagado",
            '13/03/2024,Ana Ruiz,Spain,Teclado,"10,50",pagado',
            "32/13/2024,Ana Ruiz,España,Teclado,10.00,pagado",
            "2024-03-14,Ana Ruiz,España,Teclado,,pagado",
            "2024-03-15,Ana Ruiz,Narnia,Teclado,3.00,pagado",
            "2024-01-02,  Luis   Ortega ,Mexico,Monitor,8.00,enviado",
        ]
    )
    result = clean_orders(text)
    assert result.total_rows == 6
    assert result.accepted_rows == 2
    assert result.duplicate_rows == 1
    assert result.invalid_rows == 3
    assert result.by_reason() == {"duplicate": 1, "invalid_date": 1, "empty_amount": 1, "invalid_country": 1}
    first = result.accepted[0]
    assert first.order_date == datetime(2024, 3, 13)
    assert first.country == "España"
    assert first.amount == Decimal("10.50")
    second = result.accepted[1]
    assert second.customer == "Luis Ortega"
    assert second.country == "México"


def test_missing_header_rejects_the_file() -> None:
    """A header without a required column raises CleanError before any row is kept."""
    with pytest.raises(CleanError):
        clean_orders("fecha,cliente\n2024-01-01,Ana\n")
