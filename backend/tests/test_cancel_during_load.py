"""Cancel between insert batches rolls the orders back."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import OrderRow, TaskRow
from app.db.session import make_engine, make_session_factory
from app.services.tasks import cancel_task
from worker import handler
from worker.handler import handle_import

CSV = "\n".join(
    [
        "fecha,cliente,pais,producto,importe,estado",
        "2024-03-01,Ana Ruiz,España,Teclado,10.00,pagado",
        "2024-03-02,Luis Ortega,Francia,Monitor,12.00,enviado",
    ]
) + "\n"


def test_cancel_between_batches_keeps_no_orders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> None:
    """The handler sees a cancel committed by another session and rolls the insert back."""
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "import_batch_size", 1)
    from uuid import uuid4

    task_id = uuid4()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / f"{task_id}.csv").write_text(CSV, encoding="utf-8")
    factory = make_session_factory(make_engine())
    with factory() as session:
        session.add(
            TaskRow(
                id=task_id,
                status="pending",
                filename="orders.csv",
                storage_path=f"uploads/{task_id}.csv",
                content_hash="d" * 64,
                summary={"cleaned": False},
            )
        )
        session.commit()

    def cancel_on_first(current: object) -> None:
        """Cancel from a second session the first time a batch is about to be written."""
        other: Session = factory()
        try:
            cancel_task(other, task_id)
            other.commit()
        finally:
            other.close()
        monkeypatch.setattr(handler, "before_batch", lambda task: None)

    monkeypatch.setattr(handler, "before_batch", cancel_on_first)
    result = handle_import(task_id)
    assert result.action == "ack"
    with factory() as session:
        task = session.get(TaskRow, task_id)
        assert task is not None
        assert task.status == "cancelled"
        assert task.summary["importedRows"] == 0
        count = session.query(OrderRow).filter(OrderRow.task_id == task_id).count()
        assert count == 0
