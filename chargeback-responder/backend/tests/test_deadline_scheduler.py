"""
Pure-logic tests for app/deadline_scheduler.py's check_deadlines() pass.

Only the query/escalation logic is exercised here (against the same
throwaway SQLite DB the rest of the suite uses, per conftest.py) - the
APScheduler wiring itself (start_scheduler/stop_scheduler) is a thin
wrapper around a well-tested third-party library and isn't worth
re-testing; what matters is "does a pass over the DB flag the right rows
and leave the wrong ones alone".
"""

from datetime import datetime, timezone, timedelta

import pytest

from app.database import Base, SessionLocal, engine
from app.models import Dispute
from app import deadline_scheduler


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def _make_dispute(db, id, status, deadline, requires_human_review=False):
    d = Dispute(
        id=id,
        order_id=f"order_{id}",
        reason_code="product_not_received",
        status=status,
        deadline=deadline,
        requires_human_review=requires_human_review,
        source="bank_webhook",
    )
    db.add(d)
    db.commit()
    return d


def test_escalates_pending_dispute_past_deadline():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    _make_dispute(db, "disp_overdue", "pending", now - timedelta(hours=2))
    db.close()

    escalated = deadline_scheduler.check_deadlines()

    assert escalated == 1
    db = SessionLocal()
    dispute = db.query(Dispute).filter(Dispute.id == "disp_overdue").first()
    assert dispute.requires_human_review is True
    assert "Deadline has passed" in dispute.human_review_reason
    db.close()


def test_escalates_pending_dispute_within_warning_window():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    _make_dispute(db, "disp_soon", "pending", now + timedelta(hours=6))
    db.close()

    escalated = deadline_scheduler.check_deadlines()

    assert escalated == 1
    db = SessionLocal()
    dispute = db.query(Dispute).filter(Dispute.id == "disp_soon").first()
    assert dispute.requires_human_review is True
    assert "approaching" in dispute.human_review_reason
    db.close()


def test_does_not_escalate_dispute_with_deadline_far_away():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    _make_dispute(db, "disp_plenty_of_time", "pending", now + timedelta(days=5))
    db.close()

    escalated = deadline_scheduler.check_deadlines()

    assert escalated == 0
    db = SessionLocal()
    dispute = db.query(Dispute).filter(Dispute.id == "disp_plenty_of_time").first()
    assert dispute.requires_human_review is False
    db.close()


def test_does_not_escalate_resolved_dispute_even_if_overdue():
    # Already has a decision (auto_submit) - a deadline nag on top of that
    # would be noise, not signal.
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    _make_dispute(db, "disp_resolved", "auto_submit", now - timedelta(hours=2))
    db.close()

    escalated = deadline_scheduler.check_deadlines()

    assert escalated == 0
    db = SessionLocal()
    dispute = db.query(Dispute).filter(Dispute.id == "disp_resolved").first()
    assert dispute.requires_human_review is False
    db.close()


def test_does_not_re_escalate_already_flagged_dispute():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    _make_dispute(db, "disp_already_flagged", "pending", now - timedelta(hours=2), requires_human_review=True)
    db.close()

    escalated = deadline_scheduler.check_deadlines()

    assert escalated == 0


def test_ignores_dispute_with_no_deadline():
    db = SessionLocal()
    _make_dispute(db, "disp_no_deadline", "pending", None)
    db.close()

    escalated = deadline_scheduler.check_deadlines()

    assert escalated == 0


def test_never_raises_if_db_query_fails(monkeypatch):
    def boom():
        raise RuntimeError("DB connection lost")

    monkeypatch.setattr(deadline_scheduler, "SessionLocal", boom)

    # Must degrade gracefully - a scheduler job crashing should never take
    # down the background scheduler thread.
    result = deadline_scheduler.check_deadlines()
    assert result == 0
