"""A second delivery does not insert orders twice, and a database outage naks."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.models import OrderRow, TaskRow
from app.db.session import make_engine, make_session_factory
from worker import handler
from worker.handler import handle_import

CSV = "fecha,cliente,pais,producto,importe,estado\n2024-03-13,Ana Ruiz,España,Teclado,10.00,pagado\n"


def _prepare(tmp_path: pytest.TempPathFactory | object, content_hash: str) -> object:
    """Store a one-row file and a pending task. Returns the task id."""
    settings = get_settings()
    task_id = uuid4()
    uploads = settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / f"{task_id}.csv").write_text(CSV, encoding="utf-8")
    factory = make_session_factory(make_engine())
    with factory() as session:
        session.add(
            TaskRow(
                id=task_id,
                status="pending",
                filename="orders.csv",
                storage_path=f"uploads/{task_id}.csv",
                content_hash=content_hash,
                summary={"cleaned": False},
            )
        )
        session.commit()
    return task_id


def test_completed_redelivery_does_not_insert_again(tmp_path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> None:
    """The second pass leaves the row unchanged and does not add another order."""
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    task_id = _prepare(tmp_path, "e" * 64)
    assert handle_import(task_id).action == "ack"
    assert handle_import(task_id).action == "ack"
    factory = make_session_factory(make_engine())
    with factory() as session:
        count = session.query(OrderRow).filter(OrderRow.task_id == task_id).count()
        assert count == 1


def test_processing_reclaim_inserts_once(tmp_path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> None:
    """A processing task with no committed orders is inserted once on reclaim."""
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    task_id = _prepare(tmp_path, "f" * 64)
    factory = make_session_factory(make_engine())
    with factory() as session:
        task = session.get(TaskRow, task_id)
        assert task is not None
        task.status = "processing"
        task.summary = {"cleaned": True, "totalRows": 1, "acceptedRows": 1, "rejectedRows": 0, "importedRows": 0}
        session.commit()
    assert handle_import(task_id).action == "ack"
    with factory() as session:
        count = session.query(OrderRow).filter(OrderRow.task_id == task_id).count()
        assert count == 1


def test_database_outage_naks_until_the_last_attempt(tmp_path, monkeypatch: pytest.MonkeyPatch, migrated: object) -> None:
    """A transient error naks. The last attempt stores retries_exhausted and acks."""
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    task_id = _prepare(tmp_path, "a1" * 32)

    def explode(*args: object, **kwargs: object) -> None:
        raise OperationalError("insert", {}, Exception("db down"))

    monkeypatch.setattr(handler, "_insert", explode)
    assert handle_import(task_id, attempt=1, max_deliver=4).action == "nak"
    factory = make_session_factory(make_engine())
    with factory() as session:
        task = session.get(TaskRow, task_id)
        assert task is not None
        assert task.status == "processing"
    assert handle_import(task_id, attempt=4, max_deliver=4).action == "ack"
    with factory() as session:
        task = session.get(TaskRow, task_id)
        assert task is not None
        assert task.status == "failed"
        assert task.failure_reason == "retries_exhausted"
