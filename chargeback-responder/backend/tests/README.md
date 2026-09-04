# Pure-logic test suite

Zero external dependencies: no Docker, no Postgres, no real Razorpay keys,
no Gemini key, no network access at all. Everything that would normally
call out to Postgres/Razorpay/Gemini is monkeypatched at the call site;
`conftest.py` points the DB at a throwaway SQLite file instead.

## Run it

From `backend/`, outside Docker, in a virtualenv:

```
pip install -r requirements-dev.txt
pytest -v
```

(`requirements-dev.txt` pulls in everything from `requirements.txt` plus
`pytest` - so this also needs the `crewai[google-genai]` fix already applied,
since `app/agent_pipeline.py` constructs a `crewai.LLM` object at import
time even though these tests never actually call it.)

## What's covered

- `test_razorpay_client.py` - HMAC signature verification (valid/tampered/
  replayed-for-a-different-order/no-secret-configured), the "not configured"
  fail-soft guard on every Razorpay call, and payload-building (truncation,
  optional fields) with `httpx` intercepted so nothing reaches the network.
- `test_vision_analysis.py` - every way `requires_human_review` should end
  up `True` (no key, no image, download failure, malformed model JSON,
  model call exception, low confidence, AI-generation suspected, uncertain
  claim, non-numeric confidence, missing JSON keys) *and* the flip side -
  a genuinely clean result that should NOT be forced into review.
- `test_agent_pipeline.py` - the deterministic visual verdict overriding
  the LLM crew's decision (both directions: dispute contest and refund
  claim), every fail-safe-to-`flag_for_review` path (malformed JSON,
  crashed crew, unrecognized action, crashed visual analysis), and the
  `reason_codes.yaml` lookup helpers.
- `test_main_api.py` - auth (missing/malformed/unknown token), merchant
  token auth, order ownership checks, the paid/claimed/duplicate-claim
  state machine, webhook signature verification + replay handling, and
  every branch of the manual-review endpoint (bank-webhook vs.
  customer-claim, approve vs. reject, and the Razorpay-call-fails path for
  each).

## What this deliberately does NOT cover

Whether a real Razorpay API call actually succeeds, whether a real Gemini
call returns something the parser can handle, whether the Docker/Postgres
wiring works - that's what the live-Razorpay testing guide from earlier in
this conversation is for. This suite tests *this code's own branching
logic* in isolation, not the systems it talks to.
