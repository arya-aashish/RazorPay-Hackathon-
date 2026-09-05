"""
Pure-logic tests for app/razorpay_client.py.

These deliberately don't monkeypatch httpx at all: verify_payment_signature
is pure HMAC math (no network involved regardless of config), and the
"not configured" guard on every other function returns before any request
is ever made - so testing that guard requires nothing but blanking out the
key env vars on the module object.

Anything that *would* need a real HTTP call (create_order/fetch_payment/
contest_dispute/create_refund actually succeeding) is out of scope for pure
logic tests by definition - that's what the live-Razorpay guide covers.
"""

import hashlib
import hmac

import pytest

from app import razorpay_client


def test_valid_signature_verifies(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "shh_its_a_secret")
    body = "order_abc123|pay_xyz789"
    signature = hmac.new(b"shh_its_a_secret", body.encode(), hashlib.sha256).hexdigest()

    assert razorpay_client.verify_payment_signature("order_abc123", "pay_xyz789", signature) is True


def test_tampered_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "shh_its_a_secret")
    body = "order_abc123|pay_xyz789"
    real_signature = hmac.new(b"shh_its_a_secret", body.encode(), hashlib.sha256).hexdigest()
    tampered = "f" + real_signature[1:]  # flip one character

    assert razorpay_client.verify_payment_signature("order_abc123", "pay_xyz789", tampered) is False


def test_signature_for_different_order_id_is_rejected(monkeypatch):
    # Guards against a signature computed for one order being replayed
    # against a different order/payment pair.
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "shh_its_a_secret")
    signature = hmac.new(b"shh_its_a_secret", b"order_abc123|pay_xyz789", hashlib.sha256).hexdigest()

    assert razorpay_client.verify_payment_signature("order_DIFFERENT", "pay_xyz789", signature) is False


def test_missing_secret_configured_fails_closed(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", None)
    # Even a "correctly shaped" signature must be rejected when there's no
    # secret to check it against - never treat "can't verify" as "verified".
    assert razorpay_client.verify_payment_signature("order_1", "pay_1", "anything") is False


def test_empty_signature_rejected(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "shh")
    assert razorpay_client.verify_payment_signature("order_1", "pay_1", "") is False
    assert razorpay_client.verify_payment_signature("order_1", "pay_1", None) is False


def test_create_order_without_keys_fails_soft_no_network(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", None)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", None)

    result = razorpay_client.create_order(amount_paise=49900)

    assert result == {
        "created": False,
        "order": None,
        "detail": "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured.",
    }


def test_fetch_payment_without_keys_fails_soft_no_network(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", None)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", None)

    result = razorpay_client.fetch_payment("pay_123")

    assert result["fetched"] is False
    assert result["payment"] is None


def test_contest_dispute_without_keys_fails_soft_no_network(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", None)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", None)

    result = razorpay_client.contest_dispute("disp_123", "summary", "reasoning")

    assert result["submitted"] is False
    assert result["status_code"] is None


def test_create_refund_without_keys_fails_soft_no_network(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", None)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", None)

    result = razorpay_client.create_refund("pay_123", amount_paise=1000)

    assert result["submitted"] is False
    assert result["refund"] is None


def test_create_refund_requires_an_idempotency_key(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    result = razorpay_client.create_refund("pay_123", amount_paise=1000)

    assert result["submitted"] is False
    assert "idempotency" in result["detail"].lower()


def test_create_refund_sends_razorpay_idempotency_header(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")
    captured = {}

    def fake_post(url, json, headers, auth, timeout):
        captured["headers"] = headers
        return _FakeResponse(200, {"id": "rfnd_1"})

    monkeypatch.setattr(razorpay_client.httpx, "post", fake_post)
    result = razorpay_client.create_refund("pay_123", amount_paise=1000, idempotency_key="refund-claim-123")

    assert result["submitted"] is True
    assert captured["headers"]["X-Refund-Idempotency"] == "refund-claim-123"


class _FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.text = text or str(self._json_body)

    def json(self):
        return self._json_body


def test_contest_dispute_summary_is_truncated_to_1000_chars(monkeypatch):
    # The real /contest endpoint caps 'summary' at 1000 chars - assert the
    # actual payload the client builds respects that, by intercepting the
    # outgoing call instead of letting anything reach the network.
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    captured = {}

    def fake_patch(url, json, auth, timeout):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResponse(200, {"id": "disp_1"}, text="{}")

    monkeypatch.setattr(razorpay_client.httpx, "patch", fake_patch)

    result = razorpay_client.contest_dispute("disp_123", "s" * 1200, "reasoning text is not sent as its own field")

    assert result["submitted"] is True
    assert "disp_123" in captured["url"]
    assert len(captured["payload"]["summary"]) == 1000
    # There is no "explanation" field on Razorpay's real /contest schema -
    # an earlier version of this client sent one and Razorpay would have
    # silently ignored it. Guard against that regression coming back.
    assert "explanation" not in captured["payload"]


def test_contest_dispute_always_submits_not_drafts(monkeypatch):
    # Razorpay defaults to "draft" (which explicitly does NOT submit the
    # dispute) when 'action' is omitted - this must never be left out.
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    captured = {}

    def fake_patch(url, json, auth, timeout):
        captured["payload"] = json
        return _FakeResponse(200, {"id": "disp_1"}, text="{}")

    monkeypatch.setattr(razorpay_client.httpx, "patch", fake_patch)

    razorpay_client.contest_dispute("disp_123", "summary", "reasoning")

    assert captured["payload"]["action"] == "submit"


def test_contest_dispute_attaches_document_ids_as_proof_of_service(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    captured = {}

    def fake_patch(url, json, auth, timeout):
        captured["payload"] = json
        return _FakeResponse(200, {"id": "disp_1"}, text="{}")

    monkeypatch.setattr(razorpay_client.httpx, "patch", fake_patch)

    razorpay_client.contest_dispute("disp_123", "summary", "reasoning", document_ids=["doc_abc", "doc_def"])

    assert captured["payload"]["proof_of_service"] == ["doc_abc", "doc_def"]


def test_contest_dispute_without_document_ids_omits_proof_of_service(monkeypatch):
    # No fabricated document ID - Razorpay will predictably reject a submit
    # with zero documents, and that's the correct, honest outcome rather
    # than something this client should paper over.
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    captured = {}

    def fake_patch(url, json, auth, timeout):
        captured["payload"] = json
        return _FakeResponse(200, {"id": "disp_1"}, text="{}")

    monkeypatch.setattr(razorpay_client.httpx, "patch", fake_patch)

    razorpay_client.contest_dispute("disp_123", "summary", "reasoning")

    assert "proof_of_service" not in captured["payload"]


def test_upload_evidence_document_without_keys_fails_soft_no_network(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", None)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", None)

    result = razorpay_client.upload_evidence_document(b"some evidence text", "evidence.txt")

    assert result == {"uploaded": False, "document_id": None, "detail": "RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured."}


def test_upload_evidence_document_success_returns_document_id(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    def fake_post(url, files, data, auth, timeout):
        assert data == {"purpose": "dispute_evidence"}
        assert "file" in files
        return _FakeResponse(200, {"id": "doc_EFtmUsbwpXwBH9"})

    monkeypatch.setattr(razorpay_client.httpx, "post", fake_post)

    result = razorpay_client.upload_evidence_document(b"evidence narrative", "dispute_evidence.txt")

    assert result == {"uploaded": True, "document_id": "doc_EFtmUsbwpXwBH9", "detail": ""}


def test_upload_evidence_document_surfaces_non_2xx_as_not_uploaded(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    def fake_post(url, files, data, auth, timeout):
        return _FakeResponse(400, text='{"error": {"description": "unsupported file type"}}')

    monkeypatch.setattr(razorpay_client.httpx, "post", fake_post)

    result = razorpay_client.upload_evidence_document(b"evidence narrative", "dispute_evidence.exe")

    assert result["uploaded"] is False
    assert result["document_id"] is None
    assert "400" in result["detail"]


def test_create_order_omits_receipt_and_notes_when_not_given(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    captured = {}

    def fake_post(url, json, auth, timeout):
        captured["payload"] = json
        return _FakeResponse(200, {"id": "order_1", "amount": json["amount"]})

    monkeypatch.setattr(razorpay_client.httpx, "post", fake_post)

    result = razorpay_client.create_order(amount_paise=49900)

    assert result["created"] is True
    assert "receipt" not in captured["payload"]
    assert "notes" not in captured["payload"]
    assert captured["payload"]["payment_capture"] == 1


def test_create_order_surfaces_non_2xx_as_not_created(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    def fake_post(url, json, auth, timeout):
        return _FakeResponse(400, text='{"error": {"description": "amount must be at least INR 1.00"}}')

    monkeypatch.setattr(razorpay_client.httpx, "post", fake_post)

    result = razorpay_client.create_order(amount_paise=0)

    assert result["created"] is False
    assert result["order"] is None
    assert "400" in result["detail"]


def test_create_order_never_raises_on_transport_error(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    def fake_post(*a, **k):
        raise ConnectionError("DNS resolution failed")

    monkeypatch.setattr(razorpay_client.httpx, "post", fake_post)

    # Must never raise - a network blip should degrade to a normal
    # {"created": False, ...} result the caller can react to.
    result = razorpay_client.create_order(amount_paise=49900)
    assert result["created"] is False
    assert "DNS resolution failed" in result["detail"]


# ---------------------------------------------------------------------
# Retry/backoff (tenacity). Speed up the tests instead of waiting through
# the real exponential backoff (min 0.5s * up to 3 attempts) - the thing
# under test is "does it retry the right number of times", not the actual
# timing curve.
# ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(razorpay_client, "_RETRY_DECORATOR", razorpay_client.retry(
        reraise=True,
        stop=razorpay_client.stop_after_attempt(3),
        wait=razorpay_client.wait_exponential(multiplier=0, min=0, max=0),
        retry=razorpay_client.retry_if_exception_type(
            (razorpay_client.httpx.TransportError, razorpay_client._RetryableRazorpayError)
        ),
    ))


def test_create_order_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    calls = {"n": 0}

    def flaky_post(url, json, auth, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(503, text="Service Unavailable")
        return _FakeResponse(201, {"id": "order_retried"})

    monkeypatch.setattr(razorpay_client.httpx, "post", flaky_post)

    result = razorpay_client.create_order(amount_paise=49900)

    assert result["created"] is True
    assert calls["n"] == 3  # 2 failed attempts + 1 that finally succeeded


def test_create_order_gives_up_after_max_attempts_on_persistent_5xx(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    calls = {"n": 0}

    def always_503(url, json, auth, timeout):
        calls["n"] += 1
        return _FakeResponse(503, text="Service Unavailable")

    monkeypatch.setattr(razorpay_client.httpx, "post", always_503)

    result = razorpay_client.create_order(amount_paise=49900)

    assert result["created"] is False
    assert calls["n"] == 3  # stop_after_attempt(3) - never loops forever


def test_fetch_payment_does_not_retry_on_4xx(monkeypatch):
    # A 404/400 is not transient - retrying it just burns time for the
    # same guaranteed failure, so it must return after exactly one call.
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    calls = {"n": 0}

    def not_found(url, auth, timeout):
        calls["n"] += 1
        return _FakeResponse(404, text="not found")

    monkeypatch.setattr(razorpay_client.httpx, "get", not_found)

    result = razorpay_client.fetch_payment("pay_missing")

    assert result["fetched"] is False
    assert calls["n"] == 1


def test_contest_dispute_retries_on_429(monkeypatch):
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", "fake_secret")

    calls = {"n": 0}

    def rate_limited(url, json, auth, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            return _FakeResponse(429, text="rate limited")
        return _FakeResponse(200, {"id": "disp_1"}, text="{}")

    monkeypatch.setattr(razorpay_client.httpx, "patch", rate_limited)

    result = razorpay_client.contest_dispute("disp_1", "summary", "reasoning")

    assert result["submitted"] is True
    assert calls["n"] == 2
