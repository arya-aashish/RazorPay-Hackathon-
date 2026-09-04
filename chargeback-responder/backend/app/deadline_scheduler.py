"""
Background job that watches Dispute.deadline and escalates anything getting
close to (or past) its respond-by date without a decision yet.

The webhook stores `deadline` (from Razorpay's `respond_by` field) when a
bank-initiated chargeback comes in, but nothing was ever reading it back -
a dispute could sit at status="pending" past its actual deadline and no one
would know unless they happened to open it in the dashboard. This module
closes that gap: an APScheduler job runs on an interval, finds any dispute
that's still unresolved and within (or past) a warning window of its
deadline, and flags it for human review with a reason explaining why - the
same requires_human_review flag the manual-override UI already watches, so
no frontend changes are needed for an escalated dispute to show up.

Deliberately simple for the hackathon timeline: a single in-process
APScheduler job polling on an interval, not a durable/distributed task
queue. Fine for a single backend instance; would need a real job queue
(e.g. Celery beat, or a DB-backed lock) behind more than one.
"""

import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .database import SessionLocal
from .models import Dispute

logger = logging.getLogger("chargeback_responder")

# How often the job runs.
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

# How far ahead of the deadline to start escalating - a dispute that's still
# "pending" with less than this much time left (or already past deadline)
# gets flagged, so a merchant sees it before Razorpay auto-decides against
# them for non-response.
WARNING_WINDOW = timedelta(hours=24)

# Statuses that mean "the pipeline hasn't produced a decision yet" - only
# these are eligible for deadline escalation. Anything else (auto_submit,
# approve_refund, manually_contested, action_failed, ...) already has a
# decision on record and doesn't need a deadline nag.
UNRESOLVED_STATUSES = ("pending", "evaluating")

_scheduler: BackgroundScheduler | None = None


def check_deadlines() -> int:
    """
    Runs one pass: finds unresolved disputes whose deadline is within the
    warning window (or already past) and flags them for human review.

    Returns the number of disputes escalated in this pass (mostly useful
    for tests/logging - callers don't need to do anything with it).
    """
    now = datetime.now(timezone.utc)
    cutoff = now + WARNING_WINDOW
    escalated = 0

    db = None
    try:
        db = SessionLocal()
        candidates = (
            db.query(Dispute)
            .filter(Dispute.status.in_(UNRESOLVED_STATUSES))
            .filter(Dispute.deadline.isnot(None))
            .filter(Dispute.deadline <= cutoff)
            .filter(Dispute.requires_human_review.is_(False))
            .all()
        )

        for dispute in candidates:
            deadline = dispute.deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            overdue = deadline <= now
            reason = (
                f"Deadline has passed ({deadline.isoformat()}) with no decision recorded."
                if overdue
                else f"Deadline is approaching ({deadline.isoformat()}, within {WARNING_WINDOW}) with no decision recorded."
            )

            dispute.requires_human_review = True
            dispute.human_review_reason = reason
            escalated += 1
            logger.warning(f"[deadline-scheduler] Escalated {dispute.id}: {reason}")

        if candidates:
            db.commit()
    except Exception:
        logger.exception("[deadline-scheduler] check_deadlines pass crashed")
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()

    return escalated


def start_scheduler() -> BackgroundScheduler:
    """
    Starts the background job on an interval. Idempotent - calling this
    more than once (e.g. under a dev auto-reloader) reuses the existing
    scheduler instead of starting a second one.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        check_deadlines,
        "interval",
        seconds=CHECK_INTERVAL_SECONDS,
        id="dispute_deadline_check",
        next_run_time=datetime.now(timezone.utc),  # run once immediately, then on the interval
    )
    _scheduler.start()
    logger.info(f"[deadline-scheduler] Started, checking every {CHECK_INTERVAL_SECONDS}s.")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
