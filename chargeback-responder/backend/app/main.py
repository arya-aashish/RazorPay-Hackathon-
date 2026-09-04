import os
import base64
import sys
import hmac
import secrets
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, Request, BackgroundTasks, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .security import verify_razorpay_signature
from .database import engine, get_db, Base, SessionLocal, run_dev_auto_migrations
from .models import Dispute, User, Order
from .auth import get_current_user
from .agent_pipeline import process_dispute, process_refund_claim
from . import razorpay_client
from .deadline_scheduler import start_scheduler, stop_scheduler
from .evidence_crypto import encrypt_evidence, decrypt_evidence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chargeback_responder")

# Auto-create tables, then patch in any columns a model gained since the dev
# DB volume was last created (see database.run_dev_auto_migrations docstring
# - this is what was crashing every /disputes query with
# "column disputes.source does not exist").
Base.metadata.create_all(bind=engine)
run_dev_auto_migrations()

# Merchant-side dashboard auth. Tokens are deployment-configured rather than
# compiled into the application, and more than one token can be accepted.
# without this, GET /disputes returns every customer's claim_details,
# evidence photo URL, and internal agent reasoning to anyone who requests
# it, unauthenticated. Configure one or more merchant tokens in the
# environment; there is intentionally no shared hard-coded fallback.
_merchant_tokens = [token.strip() for token in os.getenv("MERCHANT_API_TOKENS", "").split(",") if token.strip()]
if os.getenv("MERCHANT_API_TOKEN"):
    _merchant_tokens.append(os.environ["MERCHANT_API_TOKEN"])
MERCHANT_API_TOKENS = tuple(dict.fromkeys(_merchant_tokens))


def require_merchant(x_merchant_token: str = Header(None)):
    if not x_merchant_token or not any(hmac.compare_digest(x_merchant_token, token) for token in MERCHANT_API_TOKENS):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Merchant-Token header.")
    return True


def _encrypt_legacy_evidence() -> None:
    """One-way startup migration for images stored by older app versions."""
    if not os.getenv("EVIDENCE_ENCRYPTION_KEY"):
        return
    db = SessionLocal()
    try:
        changed = 0
        for dispute in db.query(Dispute).all():
            evidence = dispute.evidence_json or {}
            data_url = evidence.get("image_data")
            if not data_url or "base64," not in data_url:
                continue
            header, encoded = data_url.split(",", 1)
            mime_type = header[5:].split(";", 1)[0] if header.startswith("data:image/") else "image/jpeg"
            dispute.evidence_json = {"encrypted_image": encrypt_evidence(base64.b64decode(encoded)), "mime_type": mime_type}
            changed += 1
        if changed:
            db.commit()
            logger.info("Encrypted %d legacy evidence record(s).", changed)
    except Exception:
        db.rollback()
        logger.exception("Legacy evidence encryption migration failed.")
    finally:
        db.close()


app = FastAPI(title="Chargeback Evidence Responder")


@app.on_event("startup")
def _start_deadline_scheduler():
    # Escalates any dispute sitting unresolved close to (or past) its
    # respond-by deadline - see deadline_scheduler.py. Runs in-process
    # alongside the API. Skipped under pytest ("pytest" in sys.modules is
    # the standard trick, since TestClient(app) used as a context manager
    # fires real startup/shutdown events) - the test suite's whole premise
    # is zero external calls / no background threads outliving a test.
    _encrypt_legacy_evidence()
    if "pytest" in sys.modules:
        logger.info("[deadline-scheduler] Skipped under pytest.")
        return
    start_scheduler()


@app.on_event("shutdown")
def _stop_deadline_scheduler():
    stop_scheduler()

# The frontend (Vite dev server) runs on a different origin, and now
# actually needs to call these APIs (signup, orders, claims) - added ahead
# of that work rather than leaving it as a surprise later.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Backend is running"}


def _serialize_dispute(d: Dispute) -> dict:
    def iso_utc(value):
        if not value:
            return None
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

    evidence_image = None
    encrypted_image = (d.evidence_json or {}).get("encrypted_image")
    if encrypted_image:
        try:
            mime_type = (d.evidence_json or {}).get("mime_type", "image/jpeg")
            evidence_image = f"data:{mime_type};base64," + base64.b64encode(decrypt_evidence(encrypted_image)).decode("ascii")
        except RuntimeError:
            logger.error("Could not decrypt evidence for dispute %s", d.id)
    return {
        "id": d.id,
        "order_id": d.order_id,
        "customer_id": d.customer_id,
        "reason_code": d.reason_code,
        "source": d.source,
        "deadline": iso_utc(d.deadline),
        "status": d.status,
        "claim_details": d.claim_details,
        "customer_evidence_image_url": d.customer_evidence_image_url,
        "customer_evidence_image": evidence_image,
        "submission_result": d.submission_result,
        "requires_human_review": d.requires_human_review,
        "human_review_reason": d.human_review_reason,
        "created_at": iso_utc(d.created_at),
        "resolved_at": iso_utc(d.resolved_at),
    }


@app.get("/disputes", dependencies=[Depends(require_merchant)])
def list_disputes(db: Session = Depends(get_db)):
    disputes = db.query(Dispute).order_by(Dispute.created_at.desc()).all()
    return [_serialize_dispute(d) for d in disputes]


@app.get("/disputes/{dispute_id}", dependencies=[Depends(require_merchant)])
def get_dispute(dispute_id: str, db: Session = Depends(get_db)):
    dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return _serialize_dispute(dispute)


class ReviewAction(BaseModel):
    action: str  # "approve" or "reject"
    message: Optional[str] = Field(default=None, max_length=2000)
    # Kept temporarily so older dashboard clients keep working. New clients
    # send `message`, which is explicitly customer-facing for refund claims.
    notes: Optional[str] = None


@app.post("/disputes/{dispute_id}/review", dependencies=[Depends(require_merchant)])
def manual_review(dispute_id: str, req: ReviewAction, db: Session = Depends(get_db)):
    """
    Human-in-the-loop override for anything the agent pipeline flagged
    (requires_human_review=True) - the manual override UI is a stated
    non-negotiable alongside auto_submit/approve_refund, not an optional
    nice-to-have.

    Behavior branches on Dispute.source, because "approve" means opposite
    things depending on who's disputing:
      - bank_webhook (a bank-initiated chargeback): 'approve' contests it
        via Razorpay (defend the merchant); 'reject' means the merchant
        chooses not to contest (accepts the chargeback).
      - customer_claim (self-service refund request): 'approve' actually
        issues a refund via Razorpay (side with the customer, real money
        moves); 'reject' denies the claim.

    A real Razorpay call failure is recorded on the dispute row and
    returned as an error - never silently written down as a success.
    """
    dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    if req.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    submission_result = dict(dispute.submission_result or {})
    merchant_message = (req.message if req.message is not None else req.notes) or ""
    submission_result["manual_override"] = {
        "action": req.action,
        "merchant_message": merchant_message.strip(),
    }

    if dispute.source == "customer_claim":
        if req.action == "reject":
            dispute.status = "reject_claim"
        else:
            order = db.query(Order).filter(Order.id == dispute.order_id).first()
            if not order or not order.razorpay_payment_id:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot approve refund: no captured Razorpay payment on file for this order.",
                )
            refund = razorpay_client.create_refund(
                payment_id=order.razorpay_payment_id,
                amount_paise=order.amount,
                notes={"dispute_id": dispute_id, "manual_override": "true"},
                idempotency_key=f"refund-{dispute_id}",
            )
            submission_result["razorpay_refund"] = refund
            dispute.status = "approve_refund" if refund.get("submitted") else "action_failed"
    else:  # bank_webhook
        if req.action == "reject":
            dispute.status = "manually_not_contested"
        else:
            submission = razorpay_client.contest_dispute(
                dispute_id=dispute_id,
                evidence_summary=submission_result.get("evidence_summary", ""),
                reasoning=merchant_message or submission_result.get("reasoning", ""),
            )
            submission_result["razorpay_submission"] = submission
            dispute.status = "manually_contested" if submission.get("submitted") else "action_failed"

    dispute.submission_result = submission_result
    if dispute.status != "action_failed":
        dispute.resolved_at = datetime.now(timezone.utc)
    dispute.requires_human_review = dispute.status == "action_failed"
    if dispute.status == "action_failed":
        dispute.human_review_reason = "Manual override attempted but the Razorpay API call failed - see submission_result."
    else:
        dispute.human_review_reason = None
    db.commit()

    if dispute.status == "action_failed":
        detail = (
            submission_result.get("razorpay_refund", {}).get("detail")
            or submission_result.get("razorpay_submission", {}).get("detail")
            or "Unknown error"
        )
        raise HTTPException(status_code=502, detail=f"Razorpay call failed: {detail}")

    return {"status": "success", "dispute_id": dispute_id, "new_status": dispute.status}


# =====================================================================
# Bank-initiated chargeback flow (Razorpay -> webhook -> contest/flag)
# =====================================================================

@app.post("/webhook", dependencies=[Depends(verify_razorpay_signature)])
async def receive_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    payload = await request.json()
    event_data = payload.get("payload", {}).get("dispute", {}).get("entity", {})

    dispute_id = event_data.get("id", payload.get("dispute_id", "test_id"))
    reason_code = event_data.get("reason_code", "unknown")
    customer_id = event_data.get("customer_id", "cust_default_123")
    order_id = event_data.get("order_id") or event_data.get("payment_id") or dispute_id
    claim_details = event_data.get("claim_details", "")
    customer_evidence_image_url = event_data.get("evidence_image_url")

    deadline = None
    respond_by = event_data.get("respond_by")
    if respond_by:
        try:
            deadline = datetime.fromtimestamp(int(respond_by), tz=timezone.utc)
        except (TypeError, ValueError):
            logger.warning(f"Webhook for {dispute_id}: could not parse respond_by={respond_by!r} as a timestamp.")

    logger.info(f"Webhook received: dispute_id={dispute_id} reason_code={reason_code} customer_id={customer_id}")

    existing = db.query(Dispute).filter(Dispute.id == dispute_id).first()
    if existing:
        logger.info(f"Webhook for {dispute_id}: dispute already exists, ignoring.")
        return {"status": "ignored", "message": "Dispute already exists"}

    new_dispute = Dispute(
        id=dispute_id,
        order_id=order_id,
        customer_id=customer_id,
        reason_code=reason_code,
        deadline=deadline,
        status="pending",
        source="bank_webhook",
        claim_details=claim_details,
        customer_evidence_image_url=customer_evidence_image_url,
    )
    db.add(new_dispute)
    try:
        db.commit()
    except IntegrityError:
        # The primary-key constraint is the authoritative duplicate guard.
        # A concurrent delivery can pass the earlier read, but only one
        # transaction can insert this Razorpay dispute ID.
        db.rollback()
        logger.info("Webhook for %s: concurrent duplicate ignored.", dispute_id)
        return {"status": "ignored", "message": "Dispute already exists"}

    # Trigger AI without passing the request's DB session
    background_tasks.add_task(
        run_agent_and_update_db,
        dispute_id,
        reason_code,
        customer_id,
        order_id,
        claim_details,
        customer_evidence_image_url,
    )

    return {"status": "success", "dispute_id": dispute_id}


def run_agent_and_update_db(
    dispute_id: str,
    reason_code: str,
    customer_id: str,
    order_id: str,
    claim_details: str,
    customer_evidence_image_url,
):
    logger.info(f"Starting agent pipeline for {dispute_id}...")

    db = SessionLocal()
    try:
        try:
            result_json = process_dispute(
                dispute_id,
                reason_code,
                customer_id,
                order_id=order_id,
                claim_details=claim_details,
                customer_image_url=customer_evidence_image_url,
            )
        except Exception as exc:
            logger.exception(f"Pipeline for {dispute_id} raised an uncaught exception: {exc}")
            result_json = {
                "action": "flag_for_review",
                "reasoning": "AI analysis is currently unavailable; no decision was produced.",
                "evidence_summary": "",
                "requires_human_review": True,
                "human_review_reason": "AI analysis is currently unavailable. Please review this claim manually.",
            }

        dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
        if dispute:
            dispute.status = result_json.get("action", "flag_for_review")

            if dispute.status == "auto_submit":
                submission = razorpay_client.contest_dispute(
                    dispute_id=dispute_id,
                    evidence_summary=result_json.get("evidence_summary", ""),
                    reasoning=result_json.get("reasoning", ""),
                )
                result_json["razorpay_submission"] = submission
                if not submission.get("submitted"):
                    dispute.status = "flag_for_review"
                    result_json["action"] = "flag_for_review"
                    result_json["human_review_reason"] = (
                        f"Auto-submit decision was made but the Razorpay API call failed: "
                        f"{submission.get('detail')}"
                    )
                    logger.error(f"Razorpay submission failed for {dispute_id}, routed to human review.")

            dispute.submission_result = result_json
            dispute.requires_human_review = bool(
                result_json.get("requires_human_review", dispute.status == "flag_for_review")
            )
            dispute.human_review_reason = result_json.get("human_review_reason")
            db.commit()
            logger.info(f"Pipeline finished for {dispute_id}. Decision: {dispute.status}")
        else:
            logger.error(f"Pipeline finished for {dispute_id} but its dispute row no longer exists.")
    finally:
        db.close()


# =====================================================================
# Customer-facing flow: signup -> create order -> pay -> file a refund claim
# Every write here resolves "who is calling" from the bearer token (see
# auth.get_current_user), never from anything the client asserts in the body.
# =====================================================================

class SignupRequest(BaseModel):
    email: str
    name: Optional[str] = None


class CreateOrderRequest(BaseModel):
    amount: int = Field(gt=0, description="Amount in the smallest currency unit, e.g. paise for INR")
    currency: str = "INR"
    receipt: Optional[str] = None


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class ClaimRequest(BaseModel):
    order_id: str
    reason_code: str = Field(min_length=1, max_length=80)
    claim_details: str = Field(default="", max_length=4000)
    # A browser-selected local image, supplied as a data URL.  We do not
    # accept arbitrary remote URLs for customer evidence.
    evidence_image_data: Optional[str] = None


@app.post("/auth/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    """
    Minimal signup: email in, an opaque api_token back. No password/session -
    this is a demo-scoped auth scheme (see auth.py docstring), not something
    to ship to real production as-is. The returned api_token is shown ONCE;
    the client is responsible for holding onto it.
    """
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")

    user = User(email=req.email, name=req.name)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"New user signed up: {user.id} ({user.email})")
    return {"user_id": user.id, "email": user.email, "api_token": user.api_token}


@app.post("/orders")
def create_order_endpoint(
    req: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a real Razorpay Test Mode order and binds it to the authenticated user."""
    result = razorpay_client.create_order(
        amount_paise=req.amount,
        currency=req.currency,
        receipt=req.receipt,
        notes={"user_id": current_user.id},
    )
    if not result.get("created"):
        raise HTTPException(status_code=502, detail=f"Could not create Razorpay order: {result.get('detail')}")

    rp_order = result["order"]
    order = Order(
        id=rp_order["id"],
        user_id=current_user.id,
        amount=req.amount,
        currency=req.currency,
        receipt=req.receipt,
        status="created",
    )
    db.add(order)
    db.commit()
    logger.info(f"Order {order.id} created for user {current_user.id}")

    return {
        "order_id": rp_order["id"],
        "amount": req.amount,
        "currency": req.currency,
        # Razorpay's key_id is the public half of the credential pair and is
        # meant to be used client-side by Checkout - safe to return here.
        # RAZORPAY_KEY_SECRET is never sent to the client.
        "razorpay_key_id": razorpay_client.RAZORPAY_KEY_ID,
    }


@app.get("/orders")
def list_my_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == current_user.id).order_by(Order.created_at.desc()).all()
    payload = []
    for o in orders:
        claim = (db.query(Dispute)
                 .filter(Dispute.order_id == o.id, Dispute.source == "customer_claim")
                 .order_by(Dispute.created_at.desc()).first())
        payload.append({
            "order_id": o.id,
            "amount": o.amount,
            "currency": o.currency,
            "status": o.status,
            "razorpay_payment_id": o.razorpay_payment_id,
            "created_at": o.created_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if o.created_at else None,
            "claim_status": claim.status if claim else None,
            "claim_resolved_at": claim.resolved_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if claim and claim.resolved_at else None,
            "claim_merchant_message": ((claim.submission_result or {}).get("manual_override") or {}).get("merchant_message") if claim else None,
        })
    return payload


@app.post("/orders/{order_id}/verify-payment")
def verify_payment(
    order_id: str,
    req: VerifyPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Called by the frontend right after Razorpay Checkout succeeds. Verifies
    the signature, then independently re-confirms the payment with Razorpay
    directly (fetch_payment) rather than trusting the client's word that it
    succeeded - only then is the order marked paid.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != current_user.id:
        logger.warning(f"User {current_user.id} tried to verify payment for order {order_id} owned by {order.user_id}")
        raise HTTPException(status_code=403, detail="This order does not belong to you.")
    if req.razorpay_order_id != order_id:
        raise HTTPException(status_code=400, detail="razorpay_order_id does not match this order.")

    if not razorpay_client.verify_payment_signature(
        req.razorpay_order_id, req.razorpay_payment_id, req.razorpay_signature
    ):
        logger.warning(f"Payment signature verification FAILED for order {order_id}")
        raise HTTPException(status_code=400, detail="Payment signature verification failed.")

    fetched = razorpay_client.fetch_payment(req.razorpay_payment_id)
    if not fetched.get("fetched"):
        raise HTTPException(status_code=502, detail=f"Could not verify payment with Razorpay: {fetched.get('detail')}")

    payment = fetched["payment"]
    if payment.get("status") not in ("captured", "authorized"):
        raise HTTPException(
            status_code=400, detail=f"Payment is not in a successful state (status={payment.get('status')})."
        )

    order.status = "paid"
    order.razorpay_payment_id = req.razorpay_payment_id
    db.commit()
    logger.info(f"Order {order_id} marked paid (payment {req.razorpay_payment_id}) for user {current_user.id}")
    return {"order_id": order_id, "status": "paid"}


@app.post("/disputes/claim")
def file_refund_claim(
    req: ClaimRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Self-service refund claim. This is the endpoint the "only the order's
    owner can claim against it" requirement is about: ownership is resolved
    server-side (order.user_id vs. the authenticated token's user), so
    knowing or guessing someone else's order_id is not sufficient to file a
    claim against it - filing also requires being logged in as that order's
    actual owner.
    """
    order = db.query(Order).filter(Order.id == req.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.user_id != current_user.id:
        logger.warning(
            f"User {current_user.id} attempted to claim order {req.order_id} owned by {order.user_id} - denied."
        )
        raise HTTPException(status_code=403, detail="This order does not belong to you.")

    # Checked BEFORE the "is it paid" guard below: filing a claim flips
    # order.status to "claimed", so if this check ran second, a retry on an
    # already-claimed order would hit "order not paid" (400) instead of the
    # intended "you already filed a claim" (409) - the 409 branch would
    # never actually be reachable on the normal happy-path retry.
    existing = (
        db.query(Dispute)
        .filter(Dispute.order_id == req.order_id, Dispute.source == "customer_claim")
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"A claim already exists for this order (status={existing.status}).")

    if order.status != "paid":
        raise HTTPException(
            status_code=400,
            detail=f"Order is not in a paid state (status={order.status}); nothing to claim a refund on.",
        )

    # Re-check the payment directly with Razorpay at claim time. A locally
    # stored "paid" status is not enough to accept a refund on a payment that
    # has since failed, been reversed, or belongs to another order.
    if not order.razorpay_payment_id:
        raise HTTPException(status_code=400, detail="This order has no captured payment to refund.")
    payment_check = razorpay_client.fetch_payment(order.razorpay_payment_id)
    payment = payment_check.get("payment") or {}
    if not payment_check.get("fetched"):
        raise HTTPException(status_code=502, detail=f"Could not confirm payment with Razorpay: {payment_check.get('detail')}")
    if payment.get("status") != "captured" or payment.get("order_id") not in (None, order.id):
        raise HTTPException(status_code=400, detail="Razorpay does not confirm a captured payment for this order; a refund claim cannot be filed.")

    evidence_bytes = None
    evidence_mime = None
    if req.evidence_image_data:
        try:
            header, encoded = req.evidence_image_data.split(",", 1)
            if not header.startswith("data:image/") or ";base64" not in header:
                raise ValueError("not an image data URL")
            evidence_mime = header[5:].split(";", 1)[0]
            evidence_bytes = base64.b64decode(encoded, validate=True)
            if not evidence_bytes or len(evidence_bytes) > 8 * 1024 * 1024:
                raise ValueError("image must be between 1 byte and 8 MB")
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid evidence image: {exc}")

    encrypted_evidence = None
    if evidence_bytes:
        try:
            encrypted_evidence = encrypt_evidence(evidence_bytes)
        except RuntimeError:
            logger.error("Evidence upload rejected because encryption is not configured.")
            raise HTTPException(status_code=503, detail="Evidence upload is temporarily unavailable.")

    dispute_id = f"claim_{secrets.token_hex(8)}"
    new_dispute = Dispute(
        id=dispute_id,
        order_id=order.id,
        customer_id=current_user.id,
        reason_code=req.reason_code,
        status="pending",
        source="customer_claim",
        claim_details=req.claim_details,
        evidence_json={"encrypted_image": encrypted_evidence, "mime_type": evidence_mime} if encrypted_evidence else None,
    )
    db.add(new_dispute)
    order.status = "claimed"
    db.commit()

    background_tasks.add_task(
        run_refund_claim_and_update_db,
        dispute_id,
        req.reason_code,
        current_user.id,
        order.id,
        req.claim_details,
        evidence_bytes,
        evidence_mime,
        order.razorpay_payment_id,
        order.amount,
    )

    logger.info(f"Refund claim {dispute_id} filed by user {current_user.id} for order {order.id}")
    return {"status": "success", "dispute_id": dispute_id}


def run_refund_claim_and_update_db(
    dispute_id: str,
    reason_code: str,
    customer_id: str,
    order_id: str,
    claim_details: str,
    evidence_image_bytes,
    evidence_image_mime,
    payment_id,
    amount,
):
    logger.info(f"Starting refund-claim pipeline for {dispute_id}...")

    db = SessionLocal()
    try:
        try:
            # Financial facts are verified against Razorpay, never inferred
            # by Gemini from a claim narrative. A duplicate exists only when
            # Razorpay reports multiple captured payments for this order.
            if reason_code == "duplicate_processing":
                checked = razorpay_client.fetch_order_payments(order_id)
                if not checked.get("fetched"):
                    result_json = {"action": "flag_for_review", "requires_human_review": True,
                                   "reasoning": "Razorpay payment history could not be verified.",
                                   "evidence_summary": checked.get("detail", ""),
                                   "human_review_reason": "Could not verify duplicate-payment claim with Razorpay."}
                else:
                    captured = [p for p in checked.get("payments", []) if p.get("status") == "captured"]
                    duplicated = len(captured) >= 2
                    result_json = {"action": "approve_refund" if duplicated else "reject_claim",
                                   "requires_human_review": False,
                                   "reasoning": "Razorpay confirms multiple captured payments for this order." if duplicated else "Razorpay confirms only one captured payment for this order.",
                                   "evidence_summary": f"Razorpay returned {len(captured)} captured payment(s) for order {order_id}.",
                                   "payment_verification": {"source": "Razorpay", "captured_payment_count": len(captured)}}
            else:
                result_json = process_refund_claim(
                    dispute_id, reason_code, customer_id, order_id=order_id,
                    claim_details=claim_details, customer_image_data=evidence_image_bytes,
                    customer_image_mime_type=evidence_image_mime,
                )
        except Exception as exc:
            logger.exception(f"Refund-claim pipeline for {dispute_id} raised an uncaught exception: {exc}")
            result_json = {
                "action": "flag_for_review",
                "reasoning": "AI analysis is currently unavailable; no decision was produced.",
                "evidence_summary": "",
                "requires_human_review": True,
                "human_review_reason": "AI analysis is currently unavailable. Please review this claim manually.",
            }

        dispute = db.query(Dispute).filter(Dispute.id == dispute_id).first()
        if dispute:
            dispute.status = result_json.get("action", "flag_for_review")

            if dispute.status == "approve_refund":
                if not payment_id:
                    dispute.status = "flag_for_review"
                    result_json["action"] = "flag_for_review"
                    result_json["human_review_reason"] = (
                        "Approved for refund but this order has no captured Razorpay payment_id on file."
                    )
                    logger.error(f"Refund approved for {dispute_id} but no payment_id on order {order_id}.")
                else:
                    refund = razorpay_client.create_refund(
                        payment_id=payment_id,
                        amount_paise=amount,
                        notes={"dispute_id": dispute_id, "reason_code": reason_code},
                        idempotency_key=f"refund-{dispute_id}",
                    )
                    result_json["razorpay_refund"] = refund
                    if not refund.get("submitted"):
                        dispute.status = "flag_for_review"
                        result_json["action"] = "flag_for_review"
                        result_json["human_review_reason"] = (
                            f"Refund was approved but the Razorpay API call failed: {refund.get('detail')}"
                        )
                        logger.error(f"Razorpay refund failed for {dispute_id}, routed to human review.")

            dispute.submission_result = result_json
            dispute.requires_human_review = bool(
                result_json.get("requires_human_review", dispute.status == "flag_for_review")
            )
            dispute.human_review_reason = result_json.get("human_review_reason")
            if dispute.status in ("approve_refund", "reject_claim"):
                dispute.resolved_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Refund-claim pipeline finished for {dispute_id}. Decision: {dispute.status}")
        else:
            logger.error(f"Refund-claim pipeline finished for {dispute_id} but its dispute row no longer exists.")
    finally:
        db.close()
