"""A question runs only after the guard accepts the fake provider SQL."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.providers.fake import SPAIN_MARCH, TOP_CUSTOMERS, FakeProvider

CSV = "\n".join(
    [
        "fecha,cliente,pais,producto,importe,estado",
        "2024-03-13,Ana Ruiz,España,Teclado,10.50,pagado",
        "2024-04-02,Ana Ruiz,España,Monitor,5.00,pagado",
        "2024-03-15,Luis Ortega,Francia,Teclado,3.00,enviado",
    ]
) + "\n"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> TestClient:
    """An API that imports inline and answers with the fake provider."""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "nats_delivery", "inline")
    monkeypatch.setattr(settings, "llm_provider", "fake")
    return TestClient(create_app())


def test_spain_in_march_and_top_customers(client: TestClient) -> None:
    """The sample question sums March in España. The top-customers question reads that view."""
    uploaded = client.post("/api/v1/imports", files={"file": ("orders.csv", CSV.encode(), "text/csv")})
    assert uploaded.status_code == 202
    march = client.post("/api/v1/questions", json={"question": SPAIN_MARCH})
    assert march.status_code == 200
    body = march.json()["data"]
    assert body["rows"] == [["10.50"]]
    assert body["columns"] == ["total_amount"]
    assert body["truncated"] is True
    top = client.post("/api/v1/questions", json={"question": TOP_CUSTOMERS})
    assert top.status_code == 200
    assert "top_customers" in top.json()["data"]["sql"]


def test_invalid_payload_does_not_touch_the_database(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """mode=invalid is a 502 and the executor is not called."""
    monkeypatch.setattr(FakeProvider, "mode", "invalid")

    def explode(sql: str) -> tuple[list[str], list[list[str]]]:
        raise AssertionError(sql)

    monkeypatch.setattr("app.services.questions.execute_select", explode)
    response = client.post("/api/v1/questions", json={"question": "hola"})
    assert response.status_code == 502
    assert response.json()["data"] is None


def test_guard_rejection_names_the_rule(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A write from the model is 422 and the message names the rule, not the SQL."""
    monkeypatch.setattr(FakeProvider, "mode", "ok")

    def write(self: FakeProvider, question: str) -> tuple[str, int, int]:
        return '{"sql": "DELETE FROM orders"}', 0, 0

    monkeypatch.setattr(FakeProvider, "complete", write)
    response = client.post("/api/v1/questions", json={"question": "borra"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["msg"] == "Rejected by sql_guard: not_select"
