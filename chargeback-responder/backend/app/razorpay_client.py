"""
Real Razorpay Test Mode API calls.

Covers the order lifecycle end to end, not just the dispute-contest step:
  - create_order()            Orders API    - customer starts a purchase
  - verify_payment_signature() -             - checkout callback wasn't tampered with
  - fetch_payment()           Payments API  - authoritative, server-side payment status/amount
  - contest_dispute()         Disputes API  - respond to a bank-initiated chargeback (see agent_pipeline.process_dispute)
  - create_refund()           Refunds API   - pay a customer back (see agent_pipeline.process_refund_claim)

Every network call is wrapped in a short tenacity retry (see
_RETRY_DECORATOR below): transient failures (connection errors, timeouts,
and Razorpay 5xx/429 responses) get up to 3 attempts with exponential
backoff, so a blip in Razorpay's API or the network doesn't immediately
route a dispute to human review. A 4xx from Razorpay is treated as
non-retryable (retrying "bad request" or "not found" just burns time
before the same failure) and returns immediately.

Every function here still returns a plain dict and never raises past its
own boundary - callers should treat any {"...": False} result as "this
still needs a human," not silently proceed as if it succeeded.
"""

import os
import hmac
import hashlib
import logging

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger("chargeback_responder")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"


class _RetryableRazorpayError(Exception):
    """Raised internally to trigger a retry on a 5xx/429 Razorpay response.

    httpx doesn't raise on a non-2xx status by default (we check
    response.status_code ourselves), so this wraps that case in something
    tenacity's retry_if_exception_type can actually catch - a plain 4xx
    (bad request, unauthorized, not found) never raises this and is
    returned to the caller on the first attempt.
    """


# Shared retry policy: up to 3 attempts total (1 initial + 2 retries),
# exponential backoff starting at 0.5s and capped at 4s, only on network-
# level exceptions (httpx.TransportError covers connect/read timeouts and
# connection resets) or a 5xx/429 from Razorpay. Every attempt is logged so
# a retry is visible in the logs rather than silently eating latency.
_RETRY_DECORATOR = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type((httpx.TransportError, _RetryableRazorpayError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)


def _raise_if_retryable(response: httpx.Response) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise _RetryableRazorpayError(f"{response.status_code}: {response.text[:200]}")


def _configured() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def _auth():
    return (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)


def create_order(amount_paise: int, currency: str = "INR", receipt: str = None, notes: dict = None) -> dict:
    """
    Creates a Razorpay Order (Orders API). The frontend opens Razorpay
    Checkout against the returned order id to actually collect payment.

    amount_paise is the amount in the smallest currency unit (e.g. paise for
    INR - Rs 499.00 = 49900). Never trust a client-supplied amount for
    anything downstream (like a refund) without re-deriving it from what was
    actually stored here / confirmed via fetch_payment().

    Returns {"created": bool, "order": {...} | None, "detail": str}.
    """
    if not _configured():
        logger.warning("Razorpay create_order skipped: RAZORPAY_KEY_ID/SECRET not configured.")
        return {"created": False, "order": None, "detail": "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured."}

    payload = {
        "amount": amount_paise,
        "currency": currency,
        "payment_capture": 1,  # auto-capture on successful authorization
    }
    if receipt:
        payload["receipt"] = receipt
    if notes:
        payload["notes"] = notes

    @_RETRY_DECORATOR
    def _do_request():
        response = httpx.post(f"{RAZORPAY_BASE_URL}/orders", json=payload, auth=_auth(), timeout=15.0)
        _raise_if_retryable(response)
        return response

    try:
        response = _do_request()
        if response.status_code in (200, 201):
            return {"created": True, "order": response.json(), "detail": ""}
        logger.warning(f"Razorpay create_order failed: {response.status_code} {response.text[:300]}")
        return {"created": False, "order": None, "detail": f"{response.status_code}: {response.text[:300]}"}
    except Exception as exc:
        logger.exception(f"Razorpay create_order crashed (after retries): {exc}")
        return {"created": False, "order": None, "detail": f"Request failed: {exc}"}


def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
    """
    Verifies the signature Razorpay Checkout hands back to the frontend after
    a successful payment, per Razorpay's documented client-side integration:
    HMAC-SHA256("<order_id>|<payment_id>", key_secret).

    This proves the callback payload wasn't tampered with in transit from
    Checkout - it does NOT by itself prove the payment actually succeeded
    server-side (a replayed/forged-but-correctly-signed request is still a
    risk if you skip the next step). Callers should always follow this with
    fetch_payment() before trusting the payment happened - see
    main.py's /orders/{id}/verify-payment.
    """
    if not RAZORPAY_KEY_SECRET:
        logger.warning("Payment signature verification skipped: RAZORPAY_KEY_SECRET not configured.")
        return False

    body = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature or "")


def fetch_payment(payment_id: str) -> dict:
    """
    Fetches a payment's authoritative status/amount directly from Razorpay
    (Payments API). Always call this server-side before trusting that a
    payment succeeded - never trust the amount/status the frontend reports
    on its own, even after signature verification (see verify_payment_signature).

    Returns {"fetched": bool, "payment": {...} | None, "detail": str}.
    """
    if not _configured():
        return {"fetched": False, "payment": None, "detail": "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured."}

    @_RETRY_DECORATOR
    def _do_request():
        response = httpx.get(f"{RAZORPAY_BASE_URL}/payments/{payment_id}", auth=_auth(), timeout=15.0)
        _raise_if_retryable(response)
        return response

    try:
        response = _do_request()
        if response.status_code == 200:
            return {"fetched": True, "payment": response.json(), "detail": ""}
        logger.warning(f"Razorpay fetch_payment failed: {response.status_code} {response.text[:300]}")
        return {"fetched": False, "payment": None, "detail": f"{response.status_code}: {response.text[:300]}"}
    except Exception as exc:
        logger.exception(f"Razorpay fetch_payment crashed (after retries): {exc}")
        return {"fetched": False, "payment": None, "detail": f"Request failed: {exc}"}


def fetch_order_payments(order_id: str) -> dict:
    """Return Razorpay's authoritative payments for one order.

    This is deliberately used for duplicate-charge claims instead of asking
    an LLM to infer a financial fact from a customer's photo or prose.
    """
    if not _configured():
        return {"fetched": False, "payments": [], "detail": "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured."}

    @_RETRY_DECORATOR
    def _do_request():
        response = httpx.get(f"{RAZORPAY_BASE_URL}/orders/{order_id}/payments", auth=_auth(), timeout=15.0)
        _raise_if_retryable(response)
        return response

    try:
        response = _do_request()
        if response.status_code == 200:
            payload = response.json()
            return {"fetched": True, "payments": payload.get("items", payload if isinstance(payload, list) else []), "detail": ""}
        return {"fetched": False, "payments": [], "detail": f"{response.status_code}: {response.text[:300]}"}
    except Exception as exc:
        logger.exception(f"Razorpay fetch_order_payments crashed for {order_id}: {exc}")
        return {"fetched": False, "payments": [], "detail": f"Request failed: {exc}"}


def contest_dispute(dispute_id: str, evidence_summary: str, reasoning: str) -> dict:
    """
    Submits evidence and contests a dispute via Razorpay's Test Mode Disputes
    API. This is what executes an "auto_submit" decision from
    agent_pipeline.process_dispute() (bank-initiated chargeback flow).

    Returns {"submitted": bool, "detail": str, "status_code": int|None}.
    Never raises - a failed submission should be visible in the dispute's
    stored result and surfaced for a human to retry/handle manually, not
    crash the background task.

    NOTE: the exact evidence payload schema (which fields Razorpay's
    /contest endpoint expects) should be double-checked against Razorpay's
    current dispute-evidence API docs before the real demo run - this uses
    a reasonable minimal shape (a single text summary field) that is safe
    to submit in Test Mode but may need adjusting to match their schema
    exactly for a real submission to be accepted.
    """
    if not _configured():
        logger.warning("Razorpay submission skipped: RAZORPAY_KEY_ID/SECRET not configured.")
        return {
            "submitted": False,
            "detail": "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured.",
            "status_code": None,
        }

    url = f"{RAZORPAY_BASE_URL}/disputes/{dispute_id}/contest"
    # Razorpay's real /contest schema uses "explanation" (max 1000 chars),
    # not "reasoning" - folding both text fields into it here since we don't
    # yet upload real evidence documents via their Documents API (shipping_
    # proof/billing_proof/etc take document IDs, not free text).
    explanation = f"{evidence_summary} {reasoning}".strip()[:1000]
    payload = {
        "amount": None,  # set to the disputed amount if known; Razorpay allows omitting for full amount
        "summary": evidence_summary[:1000] if evidence_summary else None,
        "explanation": explanation or None,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    @_RETRY_DECORATOR
    def _do_request():
        response = httpx.patch(url, json=payload, auth=_auth(), timeout=15.0)
        _raise_if_retryable(response)
        return response

    try:
        response = _do_request()
        if response.status_code in (200, 201, 202):
            logger.info(f"Razorpay contest submitted for {dispute_id}: {response.status_code}")
            return {"submitted": True, "detail": response.text, "status_code": response.status_code}

        logger.warning(
            f"Razorpay contest FAILED for {dispute_id}: {response.status_code} {response.text[:300]}"
        )
        return {
            "submitted": False,
            "detail": f"Razorpay returned {response.status_code}: {response.text[:300]}",
            "status_code": response.status_code,
        }
    except Exception as exc:
        logger.exception(f"Razorpay contest call crashed for {dispute_id} (after retries): {exc}")
        return {"submitted": False, "detail": f"Request failed: {exc}", "status_code": None}


def create_refund(
    payment_id: str,
    amount_paise: int = None,
    notes: dict = None,
    idempotency_key: str = None,
) -> dict:
    """
    Issues a refund via Razorpay's Refunds API. Omitting amount_paise refunds
    the full remaining captured amount.

    This is what executes an "approve_refund" decision from
    agent_pipeline.process_refund_claim() (customer self-service claim flow)
    - the actual money movement. Only ever call this with a payment_id and
    amount that were resolved server-side (from the Order row / fetch_payment),
    never with values taken directly from client input.

    Returns {"submitted": bool, "detail": str, "refund": {...} | None}.
    """
    if not _configured():
        logger.warning("Razorpay refund skipped: RAZORPAY_KEY_ID/SECRET not configured.")
        return {"submitted": False, "detail": "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured.", "refund": None}

    if not idempotency_key or len(idempotency_key) < 10:
        return {"submitted": False, "detail": "A valid refund idempotency key is required.", "refund": None}

    payload = {}
    if amount_paise is not None:
        payload["amount"] = amount_paise
    if notes:
        payload["notes"] = notes

    # Razorpay records this key, so every retry represents the same refund
    # even if its first response was lost in transit.
    @_RETRY_DECORATOR
    def _do_request():
        response = httpx.post(
            f"{RAZORPAY_BASE_URL}/payments/{payment_id}/refund",
            json=payload,
            headers={"X-Refund-Idempotency": idempotency_key},
            auth=_auth(),
            timeout=15.0,
        )
        if response.status_code == 409:
            raise _RetryableRazorpayError("Refund with this idempotency key is still processing")
        _raise_if_retryable(response)
        return response

    try:
        response = _do_request()
        if response.status_code in (200, 201):
            logger.info(f"Razorpay refund issued for payment {payment_id}: {response.status_code}")
            return {"submitted": True, "detail": response.text, "refund": response.json()}

        logger.warning(f"Razorpay refund FAILED for {payment_id}: {response.status_code} {response.text[:300]}")
        return {
            "submitted": False,
            "detail": f"Razorpay returned {response.status_code}: {response.text[:300]}",
            "refund": None,
        }
    except Exception as exc:
        logger.exception(f"Razorpay refund crashed for {payment_id} (after retries): {exc}")
        return {"submitted": False, "detail": f"Request failed: {exc}", "refund": None}
