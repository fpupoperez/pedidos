"""The prompt shared by every provider. It names the only relations the guard allows."""

from typing import Protocol

from app.domain.countries import CANONICAL_COUNTRIES

SYSTEM_PROMPT = f"""
You answer questions about imported orders. Reply with one JSON object and no other text.
The object has one string field, sql. The value is one PostgreSQL SELECT.

Use only these relations:
- orders(order_date, customer, country, product, amount, status)
- sales_by_month_country(sale_month, country, order_count, total_amount)
- top_customers(customer, country, order_count, total_amount)

top_customers is already the global ten customers. Do not use it when the question filters by country, month, or product.
A filtered total uses orders. A month and country total may use sales_by_month_country.
sale_month and order_date are dates. Store and compare countries with these Spanish names:
{", ".join(CANONICAL_COUNTRIES)}.
""".strip()


class ModelProvider(Protocol):
    """One model call. The text is parsed by the question service, not executed raw."""

    name: str
    model: str

    def complete(self, question: str) -> tuple[str, int, int]:
        """Return the model text, input tokens, and output tokens."""
