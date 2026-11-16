"""Write a deterministic sample CSV of at least 1,000 orders, including planted defects."""

import random
from pathlib import Path

from app.domain.countries import CANONICAL_COUNTRIES

SEED = 20261116
GOOD_ROWS = 1000
DUPLICATE_ROWS = 25
BAD_DATE_ROWS = 15
EMPTY_AMOUNT_ROWS = 15
CUSTOMERS = ("Ana Ruiz", "Luis Ortega", "Marta Diaz", "Pedro Navas", "Elena Costa")
PRODUCTS = ("Teclado", "Monitor", "Silla", "Cable", "Lampara")
STATUSES = ("pagado", "pendiente", "enviado")


def build_csv() -> str:
    """Return the sample document. The same seed always produces the same text."""
    rng = random.Random(SEED)
    lines = ["fecha,cliente,pais,producto,importe,estado"]
    good: list[str] = []
    for index in range(GOOD_ROWS):
        day = (index % 27) + 1
        month = (index % 12) + 1
        if index == 0:
            date = "13/03/2024"
        else:
            date = f"2024-{month:02d}-{day:02d}"
        customer = rng.choice(CUSTOMERS)
        country = rng.choice(CANONICAL_COUNTRIES)
        product = rng.choice(PRODUCTS)
        amount = f"{(index % 90) + 10}.50"
        status = rng.choice(STATUSES)
        row = f"{date},{customer},{country},{product},{amount},{status}"
        good.append(row)
        lines.append(row)
    for index in range(DUPLICATE_ROWS):
        lines.append(good[index])
    bad_dates = ["32/13/2024", "marzo", ""]
    for index in range(BAD_DATE_ROWS):
        lines.append(f"{bad_dates[index % 3]},Ana Ruiz,España,Teclado,10.00,pagado")
    for _ in range(EMPTY_AMOUNT_ROWS):
        lines.append("2024-01-02,Ana Ruiz,España,Teclado,,pagado")
    return "\n".join(lines) + "\n"


def main() -> None:
    """Write orders/data/samples/orders.csv relative to the repository root."""
    root = Path(__file__).resolve().parents[1]
    target = root / "data" / "samples" / "orders.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_csv(), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
