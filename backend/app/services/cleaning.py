"""Turn one CSV text into accepted orders and per-row rejections.

This function does not touch the database. A bad row is recorded and the next row is read.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.domain.countries import canonical_country

_HEADER_ALIASES = {
    "fecha": "order_date",
    "date": "order_date",
    "cliente": "customer",
    "customer": "customer",
    "pais": "country",
    "country": "country",
    "producto": "product",
    "product": "product",
    "importe": "amount",
    "amount": "amount",
    "estado": "status",
    "status": "status",
}
_REQUIRED = ("order_date", "customer", "country", "product", "amount", "status")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


class CleanError(Exception):
    """The file cannot be cleaned. The message is safe to show to the caller."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class CleanOrder:
    """One row that passed validation."""

    source_line: int
    order_date: datetime
    customer: str
    country: str
    product: str
    amount: Decimal
    status: str


@dataclass(frozen=True)
class Rejection:
    """One row that was not imported, with the reason and the original line."""

    source_line: int
    reason: str
    raw: str


@dataclass(frozen=True)
class CleanResult:
    """Accepted rows, rejected rows, and the counts stored on the task summary."""

    accepted: list[CleanOrder]
    rejections: list[Rejection]

    @property
    def total_rows(self) -> int:
        """Data rows in the file, header excluded."""
        return len(self.accepted) + len(self.rejections)

    @property
    def accepted_rows(self) -> int:
        """Rows that will be written to orders."""
        return len(self.accepted)

    @property
    def duplicate_rows(self) -> int:
        """Extra copies of a business row. The first copy stays accepted."""
        return sum(1 for row in self.rejections if row.reason == "duplicate")

    @property
    def invalid_rows(self) -> int:
        """Rows rejected for a broken value."""
        return len(self.rejections) - self.duplicate_rows

    @property
    def rejected_rows(self) -> int:
        """Duplicates plus invalid rows."""
        return len(self.rejections)

    def by_reason(self) -> dict[str, int]:
        """Rejection counts. Reasons with a zero count are omitted."""
        counts: dict[str, int] = {}
        for row in self.rejections:
            counts[row.reason] = counts.get(row.reason, 0) + 1
        return counts


def clean_orders(text: str) -> CleanResult:
    """Clean a whole CSV document.

    Raises CleanError when the header is missing a required column.
    A bad data row becomes a Rejection and does not stop the file.
    """
    lines = text.splitlines()
    if not lines:
        raise CleanError("The CSV has no header.")
    header = _map_header(lines[0])
    accepted: list[CleanOrder] = []
    rejections: list[Rejection] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for offset, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = _split_csv_line(line)
        raw = line
        if len(cells) < len(_REQUIRED):
            rejections.append(Rejection(offset, "missing_column", raw))
            continue
        values = {name: cells[index].strip() for name, index in header.items()}
        rejection = _reject_row(values)
        if rejection is not None:
            rejections.append(Rejection(offset, rejection, raw))
            continue
        order = _build_order(offset, values)
        key = _business_key(order)
        if key in seen:
            rejections.append(Rejection(offset, "duplicate", raw))
            continue
        seen.add(key)
        accepted.append(order)
    return CleanResult(accepted=accepted, rejections=rejections)


def _map_header(line: str) -> dict[str, int]:
    """Map required fields to column indexes. Raises CleanError when one is missing."""
    cells = [cell.strip().lower() for cell in _split_csv_line(line)]
    found: dict[str, int] = {}
    for index, cell in enumerate(cells):
        name = _HEADER_ALIASES.get(cell)
        if name and name not in found:
            found[name] = index
    missing = [name for name in _REQUIRED if name not in found]
    if missing:
        raise CleanError("The CSV header is missing: " + ", ".join(missing))
    return found


def _reject_row(values: dict[str, str]) -> str | None:
    """Return a rejection reason, or None when the row can be built."""
    if not values["customer"]:
        return "empty_customer"
    if not values["country"]:
        return "empty_country"
    if canonical_country(values["country"]) is None:
        return "invalid_country"
    if not values["product"]:
        return "empty_product"
    if _parse_date(values["order_date"]) is None:
        return "invalid_date"
    if values["amount"] == "":
        return "empty_amount"
    if _parse_amount(values["amount"]) is None:
        return "invalid_amount"
    return None


def _build_order(source_line: int, values: dict[str, str]) -> CleanOrder:
    """Build an accepted order. The caller has already rejected invalid cells."""
    order_date = _parse_date(values["order_date"])
    amount = _parse_amount(values["amount"])
    country = canonical_country(values["country"])
    if order_date is None or amount is None or country is None:
        raise CleanError("An accepted row failed to parse.")
    return CleanOrder(
        source_line=source_line,
        order_date=order_date,
        customer=_collapse(values["customer"]),
        country=country,
        product=_collapse(values["product"]),
        amount=amount,
        status=values["status"].strip(),
    )


def _business_key(order: CleanOrder) -> tuple[str, str, str, str, str, str]:
    """The six business fields that define a duplicate inside one file."""
    return (
        order.order_date.date().isoformat(),
        order.customer,
        order.country,
        order.product,
        format(order.amount, "f"),
        order.status,
    )


def _parse_date(value: str) -> datetime | None:
    """Accept ISO and European dates. An impossible calendar day is rejected."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_amount(value: str) -> Decimal | None:
    """Accept a dot or a single comma as the decimal separator. Negatives are rejected."""
    text = value.strip().replace(" ", "")
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return amount


def _collapse(value: str) -> str:
    """Trim and collapse internal whitespace."""
    return " ".join(value.split())


def _split_csv_line(line: str) -> list[str]:
    """Split one CSV record. A comma decimal must be quoted, as in \"10,50\"."""
    return next(csv.reader([line]))
