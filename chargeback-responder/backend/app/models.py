import secrets
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Text, Integer
from datetime import datetime, timedelta
import os
from .database import Base


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _generate_user_id() -> str:
    return "user_" + secrets.token_hex(10)


def _token_expiry() -> datetime:
    try:
        hours = int(os.getenv("CUSTOMER_TOKEN_TTL_HOURS", "24"))
    except ValueError:
        hours = 24
    return datetime.utcnow() + timedelta(hours=max(1, hours))


class User(Base):
    """
    Minimal user record for the self-service refund-claim flow. Each user
    gets an opaque bearer api_token at signup (see POST /auth/signup) - every
    order-creation and claim-filing request must present it, and the acting
    user is always resolved from THAT token server-side, never from a
    client-supplied user_id. That's what makes order ownership checks (see
    Order.user_id below, and POST /disputes/claim in main.py) meaningful
    instead of trivially spoofable by anyone who knows/guesses an order_id.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_generate_user_id)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    api_token = Column(String, unique=True, index=True, default=_generate_token)
    token_expires_at = Column(DateTime, default=_token_expiry, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    """
    A Razorpay order, bound to the user who created it. This binding is the
    whole point: POST /disputes/claim only lets Order.user_id file a refund
    claim against Order.id, and that check is server-side against the
    authenticated user - not against anything the client asserts.
    """
    __tablename__ = "orders"

    id = Column(String, primary_key=True)  # Razorpay order id, e.g. "order_..."
    user_id = Column(String, index=True, nullable=False)  # owner - FK to User.id (no ORM relationship, kept simple)
    amount = Column(Integer, nullable=False)  # smallest currency unit (e.g. paise for INR)
    currency = Column(String, default="INR")
    receipt = Column(String, nullable=True)
    status = Column(String, default="created")  # created, paid, claimed
    razorpay_payment_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Dispute(Base):
    __tablename__ = "disputes"

    id = Column(String, primary_key=True, index=True) # Razorpay dispute ID, or a generated claim ID
    order_id = Column(String, index=True, nullable=True) # Falls back to id if not provided
    customer_id = Column(String, nullable=True)
    reason_code = Column(String, index=True)
    deadline = Column(DateTime, nullable=True)
    status = Column(String, default="pending")
    # For source="bank_webhook": pending, auto_submit, flag_for_review
    # For source="customer_claim": pending, approve_refund, reject_claim, flag_for_review
    source = Column(String, default="bank_webhook")  # 'bank_webhook' (Razorpay dispute webhook) or 'customer_claim' (self-service portal)
    claim_details = Column(Text, nullable=True) # Customer's free-text claim, e.g. "item arrived in wrong color"
    customer_evidence_image_url = Column(String, nullable=True) # Photo the customer submitted with the claim
    evidence_json = Column(JSON, nullable=True)
    submission_result = Column(JSON, nullable=True) # Full agent decision, including 'visual_evidence' and 'razorpay_submission'/'razorpay_refund' when present
    requires_human_review = Column(Boolean, default=False)
    human_review_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Set when a merchant or the deterministic pipeline reaches a terminal
    # decision.  Keeping this distinct from created_at prevents the portal
    # from presenting a made-up / stale claim time as a resolution time.
    resolved_at = Column(DateTime, nullable=True)
