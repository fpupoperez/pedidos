"""The prompt shared by every provider. It names the only relations the guard allows."""

from typing import Protocol

from app.domain.countries import CANONICAL_COUNTRIES

SYSTEM_PROMPT = f"""
You answer questions about imported orders.
Reply with this JSON object and no other text, no Markdown, and no extra keys:
{{"sql": "<one PostgreSQL SELECT>"}}

Use only these relations:
- orders(order_date, customer, country, product, amount, status)
- sales_by_month_country(sale_month, country, order_count, total_amount)
- top_customers(customer, country, order_count, total_amount)

top_customers is already the global ten customers. Do not use it when the question filters by country, month, or product.
A filtered total uses orders. A month and country total may use sales_by_month_country.
sale_month and order_date are dates. The question may be in any language.
Store and compare countries with these Spanish names:
{", ".join(CANONICAL_COUNTRIES)}.
Translate a country from the question into one of those names.
Product names are stored in Spanish. Use a stored product name from the request, not the question's word.
Do not invent a year or a BETWEEN range. Use a year only when the question names one.
A month with no year is EXTRACT(MONTH FROM order_date) = that month number.
'este año' and 'este mes' use today's date from the request, not the years stored in the table.
'cuántas' or 'cuántos' asks how many rows. Answer with COALESCE(COUNT(*), 0) AS sales.
Do not use SUM(amount) for how many sales. 'cuánto vendimos' is COALESCE(SUM(amount), 0) AS total_amount.
""".strip()


class ModelProvider(Protocol):
    """One model call. The text is parsed by the question service, not executed raw."""

    name: str
    model: str

    def complete(self, question: str) -> tuple[str, int, int]:
        """Return the model text, input tokens, and output tokens."""
