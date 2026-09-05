"""
Exercises main.py's endpoint logic end-to-end through FastAPI's TestClient,
against a throwaway SQLite database (see conftest.py for the DATABASE_URL
env var), with every external call (Razorpay, the CrewAI pipeline)
monkeypatched to a canned response. Nothing here needs Docker, Postgres,
real Razorpay keys, or a Gemini key - it's testing main.py's own branching
logic (auth, ownership checks, status guards, review-action routing), not
the systems it calls out to.

Note on background tasks: FastAPI's TestClient runs BackgroundTasks
synchronously as part of the request/response cycle, so `client.post(...)`
returning is enough of a guarantee that `run_agent_and_update_db` /
`run_refund_claim_and_update_db` have already finished and committed.
"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.database import Base, SessionLocal, engine
from app.models import Dispute, Order

WEBHOOK_SECRET = "test_webhook_secret"  # matches conftest.py's RAZORPAY_WEBHOOK_SECRET
MERCHANT_TOKEN = "test_merchant_token"  # matches conftest.py's MERCHANT_API_TOKEN


@pytest.fixture(autouse=True)
def clean_db():
    """Fresh tables for every test - these tests intentionally share no state."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client(monkeypatch):
    # Agent pipeline: canned decisions, no real LLM/vision call.
    monkeypatch.setattr(
        main_module,
        "process_dispute",
        lambda *a, **k: {
            "action": "auto_submit",
            "reasoning": "stubbed for test",
            "evidence_summary": "stubbed for test",
            "requires_human_review": False,
        },
    )
    monkeypatch.setattr(
        main_module,
        "process_refund_claim",
        lambda *a, **k: {
            "action": "flag_for_review",
            "reasoning": "stubbed for test",
            "evidence_summary": "stubbed for test",
            "requires_human_review": True,
        },
    )

    # Razorpay client: canned success responses, no real HTTP call.
    monkeypatch.setattr(
        main_module.razorpay_client,
        "create_order",
        lambda **k: {
            "created": True,
            "order": {"id": f"order_test_{int(time.time() * 1000)}"},
            "detail": "",
        },
    )
    monkeypatch.setattr(
        main_module.razorpay_client, "verify_payment_signature", lambda *a, **k: True
    )
    monkeypatch.setattr(
        main_module.razorpay_client,
        "fetch_payment",
        lambda payment_id: {"fetched": True, "payment": {"status": "captured"}, "detail": ""},
    )
    monkeypatch.setattr(
        main_module.razorpay_client,
        "upload_evidence_document",
        lambda **k: {"uploaded": True, "document_id": "doc_test_1", "detail": ""},
    )
    monkeypatch.setattr(
        main_module.razorpay_client,
        "contest_dispute",
        lambda **k: {"submitted": True, "detail": "ok", "status_code": 200},
    )
    monkeypatch.setattr(
        main_module.razorpay_client,
        "create_refund",
        lambda **k: {"submitted": True, "detail": "ok", "refund": {"id": "rfnd_test_1"}},
    )

    with TestClient(main_module.app) as c:
        yield c


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _signup(client, email):
    resp = client.post("/auth/signup", json={"email": email})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth_headers(user):
    return {"Authorization": f"Bearer {user['api_token']}"}


def _insert_dispute(**kwargs):
    db = SessionLocal()
    try:
        defaults = dict(status="pending", requires_human_review=True)
        defaults.update(kwargs)
        d = Dispute(**defaults)
        db.add(d)
        db.commit()
    finally:
        db.close()


def _insert_order(**kwargs):
    db = SessionLocal()
    try:
        defaults = dict(user_id="user_dummy", amount=49900, currency="INR", status="paid")
        defaults.update(kwargs)
        o = Order(**defaults)
        db.add(o)
        db.commit()
    finally:
        db.close()


# --- Auth -----------------------------------------------------------------

def test_missing_auth_header_rejected(client):
    resp = client.post("/orders", json={"amount": 49900})
    assert resp.status_code == 401


def test_malformed_auth_header_rejected(client):
    resp = client.get("/orders", headers={"Authorization": "not-a-bearer-token"})
    assert resp.status_code == 401


def test_unknown_token_rejected(client):
    resp = client.get("/orders", headers={"Authorization": "Bearer totally-made-up-token"})
    assert resp.status_code == 401


def test_signup_then_authenticated_call_succeeds(client):
    user = _signup(client, "alice@example.com")
    resp = client.get("/orders", headers=_auth_headers(user))
    assert resp.status_code == 200
    assert resp.json() == []


def test_duplicate_signup_email_conflicts(client):
    _signup(client, "dupe@example.com")
    resp = client.post("/auth/signup", json={"email": "dupe@example.com"})
    assert resp.status_code == 409


def test_merchant_endpoints_require_correct_token(client):
    assert client.get("/disputes").status_code == 401
    assert client.get("/disputes", headers={"X-Merchant-Token": "wrong"}).status_code == 401
    assert client.get("/disputes", headers={"X-Merchant-Token": MERCHANT_TOKEN}).status_code == 200


# --- Order + claim ownership flow ------------------------------------------

def test_cross_user_claim_is_denied(client):
    alice = _signup(client, "alice2@example.com")
    bob = _signup(client, "bob2@example.com")

    order_resp = client.post("/orders", json={"amount": 49900}, headers=_auth_headers(alice))
    assert order_resp.status_code == 200
    order_id = order_resp.json()["order_id"]

    claim_resp = client.post(
        "/disputes/claim",
        json={"order_id": order_id, "reason_code": "not_as_described", "claim_details": "not mine"},
        headers=_auth_headers(bob),
    )
    assert claim_resp.status_code == 403


def test_claim_on_unpaid_order_is_rejected(client):
    alice = _signup(client, "alice3@example.com")
    order_resp = client.post("/orders", json={"amount": 49900}, headers=_auth_headers(alice))
    order_id = order_resp.json()["order_id"]

    resp = client.post(
        "/disputes/claim",
        json={"order_id": order_id, "reason_code": "not_as_described", "claim_details": "never arrived"},
        headers=_auth_headers(alice),
    )
    assert resp.status_code == 400


def test_full_pay_then_claim_then_duplicate_claim_rejected(client):
    alice = _signup(client, "alice4@example.com")
    order_resp = client.post("/orders", json={"amount": 49900}, headers=_auth_headers(alice))
    order_id = order_resp.json()["order_id"]

    verify_resp = client.post(
        f"/orders/{order_id}/verify-payment",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_fake_1",
            "razorpay_signature": "irrelevant-since-verify_payment_signature-is-mocked",
        },
        headers=_auth_headers(alice),
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "paid"

    claim_resp = client.post(
        "/disputes/claim",
        json={"order_id": order_id, "reason_code": "not_as_described", "claim_details": "wrong color"},
        headers=_auth_headers(alice),
    )
    assert claim_resp.status_code == 200
    dispute_id = claim_resp.json()["dispute_id"]

    # Background task already ran (see module docstring) - the stubbed
    # process_refund_claim always returns flag_for_review.
    get_resp = client.get(f"/disputes/{dispute_id}", headers={"X-Merchant-Token": MERCHANT_TOKEN})
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "flag_for_review"

    # Regression guard for a real bug this test suite caught: main.py used
    # to check "is it paid" before "does a claim already exist", and since
    # filing a claim flips order.status to "claimed", a second attempt hit
    # a misleading 400 "not paid" instead of 409 "already claimed". The
    # existing-claim check now runs first.
    dup_resp = client.post(
        "/disputes/claim",
        json={"order_id": order_id, "reason_code": "not_as_described", "claim_details": "again"},
        headers=_auth_headers(alice),
    )
    assert dup_resp.status_code == 409


def test_order_color_is_persisted_and_passed_to_claim_analysis(client, monkeypatch):
    captured = {}

    def _claim_pipeline(*args, **kwargs):
        captured.update(kwargs)
        return {
            "action": "flag_for_review",
            "reasoning": "stubbed for test",
            "evidence_summary": "stubbed for test",
            "requires_human_review": True,
        }

    monkeypatch.setattr(main_module, "process_refund_claim", _claim_pipeline)
    alice = _signup(client, "color-order@example.com")
    headers = _auth_headers(alice)
    order_resp = client.post(
        "/orders", json={"amount": 49900, "product_color": "Navy blue"}, headers=headers
    )
    assert order_resp.status_code == 200
    order_id = order_resp.json()["order_id"]
    assert order_resp.json()["product_color"] == "Navy blue"

    listed = client.get("/orders", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["product_color"] == "Navy blue"

    verify_resp = client.post(
        f"/orders/{order_id}/verify-payment",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_color_1",
            "razorpay_signature": "test-signature",
        },
        headers=headers,
    )
    assert verify_resp.status_code == 200
    claim_resp = client.post(
        "/disputes/claim",
        json={"order_id": order_id, "reason_code": "not_as_described", "claim_details": "wrong color"},
        headers=headers,
    )
    assert claim_resp.status_code == 200
    assert captured["ordered_product_color"] == "Navy blue"


def test_verify_payment_rejects_mismatched_order_id(client):
    alice = _signup(client, "alice5@example.com")
    order_resp = client.post("/orders", json={"amount": 49900}, headers=_auth_headers(alice))
    order_id = order_resp.json()["order_id"]

    resp = client.post(
        f"/orders/{order_id}/verify-payment",
        json={
            "razorpay_order_id": "order_some_other_id",
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": "sig",
        },
        headers=_auth_headers(alice),
    )
    assert resp.status_code == 400


def test_verify_payment_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(main_module.razorpay_client, "verify_payment_signature", lambda *a, **k: False)

    alice = _signup(client, "alice6@example.com")
    order_resp = client.post("/orders", json={"amount": 49900}, headers=_auth_headers(alice))
    order_id = order_resp.json()["order_id"]

    resp = client.post(
        f"/orders/{order_id}/verify-payment",
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_1", "razorpay_signature": "bad"},
        headers=_auth_headers(alice),
    )
    assert resp.status_code == 400


def test_verify_payment_rejects_non_captured_status(client, monkeypatch):
    monkeypatch.setattr(
        main_module.razorpay_client,
        "fetch_payment",
        lambda payment_id: {"fetched": True, "payment": {"status": "failed"}, "detail": ""},
    )

    alice = _signup(client, "alice7@example.com")
    order_resp = client.post("/orders", json={"amount": 49900}, headers=_auth_headers(alice))
    order_id = order_resp.json()["order_id"]

    resp = client.post(
        f"/orders/{order_id}/verify-payment",
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_1", "razorpay_signature": "sig"},
        headers=_auth_headers(alice),
    )
    assert resp.status_code == 400


# --- Webhook (bank-initiated disputes) --------------------------------------

def _dispute_payload(dispute_id="disp_test_1", reason_code="product_not_received"):
    return {
        "event": "payment.dispute.created",
        "payload": {
            "dispute": {
                "entity": {
                    "id": dispute_id,
                    "reason_code": reason_code,
                    "customer_id": "cust_1@example.com",
                    "order_id": "order_1",
                    "claim_details": "test claim",
                    "respond_by": int(time.time()) + 3 * 24 * 60 * 60,
                }
            }
        },
    }


def test_webhook_missing_signature_header_rejected(client):
    body = json.dumps(_dispute_payload()).encode()
    resp = client.post("/webhook", content=body)
    assert resp.status_code == 401


def test_webhook_bad_signature_rejected(client):
    body = json.dumps(_dispute_payload()).encode()
    resp = client.post("/webhook", content=body, headers={"X-Razorpay-Signature": "not-the-real-signature"})
    assert resp.status_code == 401


def test_webhook_valid_signature_creates_dispute(client):
    body = json.dumps(_dispute_payload(dispute_id="disp_valid_1")).encode()
    resp = client.post("/webhook", content=body, headers={"X-Razorpay-Signature": _sign(body)})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    get_resp = client.get("/disputes/disp_valid_1", headers={"X-Merchant-Token": MERCHANT_TOKEN})
    assert get_resp.status_code == 200
    # process_dispute is stubbed to always return auto_submit + contest_dispute stubbed to succeed
    assert get_resp.json()["status"] == "auto_submit"


def test_webhook_replay_is_ignored_not_duplicated(client):
    body = json.dumps(_dispute_payload(dispute_id="disp_replay_1")).encode()
    signature = _sign(body)

    first = client.post("/webhook", content=body, headers={"X-Razorpay-Signature": signature})
    assert first.status_code == 200
    assert first.json()["status"] == "success"

    second = client.post("/webhook", content=body, headers={"X-Razorpay-Signature": signature})
    assert second.status_code == 200
    assert second.json()["status"] == "ignored"

    all_disputes = client.get("/disputes", headers={"X-Merchant-Token": MERCHANT_TOKEN}).json()
    matching = [d for d in all_disputes if d["id"] == "disp_replay_1"]
    assert len(matching) == 1


def test_webhook_auto_submit_routed_to_review_when_razorpay_call_fails(client, monkeypatch):
    monkeypatch.setattr(
        main_module.razorpay_client,
        "contest_dispute",
        lambda **k: {"submitted": False, "detail": "Razorpay returned 500", "status_code": 500},
    )

    body = json.dumps(_dispute_payload(dispute_id="disp_failcase_1")).encode()
    resp = client.post("/webhook", content=body, headers={"X-Razorpay-Signature": _sign(body)})
    assert resp.status_code == 200

    get_resp = client.get("/disputes/disp_failcase_1", headers={"X-Merchant-Token": MERCHANT_TOKEN})
    payload = get_resp.json()
    # The pipeline said auto_submit, but since the real Razorpay call
    # failed, this must NOT be silently recorded as a success.
    assert payload["status"] == "flag_for_review"
    assert payload["requires_human_review"] is True


# --- Manual review branching -------------------------------------------

def test_manual_review_unknown_dispute_404(client):
    resp = client.post(
        "/disputes/does_not_exist/review",
        json={"action": "approve"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 404


def test_manual_review_invalid_action_rejected(client):
    _insert_dispute(id="d_bad_action", order_id="o1", source="bank_webhook")
    resp = client.post(
        "/disputes/d_bad_action/review",
        json={"action": "sort-of-approve"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 400


def test_manual_review_bank_webhook_reject(client):
    _insert_dispute(id="d_bw_reject", order_id="o1", source="bank_webhook")
    resp = client.post(
        "/disputes/d_bw_reject/review",
        json={"action": "reject"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "manually_not_contested"


def test_manual_review_bank_webhook_approve_contests_via_razorpay(client):
    _insert_dispute(id="d_bw_approve", order_id="o1", source="bank_webhook")
    resp = client.post(
        "/disputes/d_bw_approve/review",
        json={"action": "approve", "notes": "clear evidence on review"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "manually_contested"


def test_manual_review_bank_webhook_approve_surfaces_razorpay_failure(client, monkeypatch):
    monkeypatch.setattr(
        main_module.razorpay_client,
        "contest_dispute",
        lambda **k: {"submitted": False, "detail": "Razorpay returned 500", "status_code": 500},
    )
    _insert_dispute(id="d_bw_fail", order_id="o1", source="bank_webhook")

    resp = client.post(
        "/disputes/d_bw_fail/review",
        json={"action": "approve"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 502

    get_resp = client.get("/disputes/d_bw_fail", headers={"X-Merchant-Token": MERCHANT_TOKEN})
    assert get_resp.json()["status"] == "action_failed"
    assert get_resp.json()["requires_human_review"] is True


def test_manual_review_customer_claim_reject(client):
    _insert_order(id="o_claim_1", razorpay_payment_id="pay_1")
    _insert_dispute(id="d_cc_reject", order_id="o_claim_1", source="customer_claim")

    resp = client.post(
        "/disputes/d_cc_reject/review",
        json={"action": "reject"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "reject_claim"


def test_manual_review_customer_claim_approve_without_payment_id_errors(client):
    _insert_order(id="o_claim_2", razorpay_payment_id=None)
    _insert_dispute(id="d_cc_no_payment", order_id="o_claim_2", source="customer_claim")

    resp = client.post(
        "/disputes/d_cc_no_payment/review",
        json={"action": "approve"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 400


def test_manual_review_customer_claim_approve_issues_real_refund_call(client):
    _insert_order(id="o_claim_3", razorpay_payment_id="pay_captured_1")
    _insert_dispute(id="d_cc_approve", order_id="o_claim_3", source="customer_claim")

    resp = client.post(
        "/disputes/d_cc_approve/review",
        json={"action": "approve"},
        headers={"X-Merchant-Token": MERCHANT_TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "approve_refund"
