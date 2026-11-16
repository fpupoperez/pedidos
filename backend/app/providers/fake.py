"""A fixed map from question text to SQL. It does not open a socket."""

import json

SPAIN_MARCH = "¿cuánto vendimos en España en marzo?"
TOP_CUSTOMERS = "¿cuáles son los 10 mejores clientes?"

_SPAIN_SQL = (
    "SELECT COALESCE(SUM(amount), 0) AS total_amount FROM orders "
    "WHERE country = 'España' AND EXTRACT(MONTH FROM order_date) = 3"
)
_TOP_SQL = "SELECT customer, country, total_amount FROM top_customers"
_SAFE_SQL = "SELECT country, total_amount FROM sales_by_month_country"

_ANSWERS = {
    " ".join(SPAIN_MARCH.casefold().split()): _SPAIN_SQL,
    " ".join(TOP_CUSTOMERS.casefold().split()): _TOP_SQL,
}


class FakeProvider:
    """Return known SQL, a safe select, or a payload the parser must reject.

    mode is invalid only when a test sets it. The default never returns a write.
    """

    mode = "ok"
    name = "fake"
    model = "fake"

    def complete(self, question: str) -> tuple[str, int, int]:
        """Return model text, input tokens, and output tokens. Tokens stay at zero."""
        if self.mode == "invalid":
            return "not-json", 0, 0
        key = " ".join(question.strip().casefold().split())
        sql = _ANSWERS.get(key, _SAFE_SQL)
        return json.dumps({"sql": sql}), 0, 0
