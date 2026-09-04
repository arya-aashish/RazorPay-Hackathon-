"""
Shared test setup. pytest loads conftest.py for a directory before it
imports any test module in that directory, which is exactly what we need
here: every env var below must be set BEFORE `app.database` / `app.main` /
`app.agent_pipeline` are first imported anywhere in the test session,
because each of those modules reads its config from os.environ at import
time (module-level constants), not lazily.

None of these values are real credentials. The whole point of this test
suite is that it never talks to Postgres, Razorpay, or Gemini - external
calls are monkeypatched out at the call site in each test file instead.
"""

import os
import tempfile

_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "chargeback_responder_pure_tests.db")

# Remove any leftover DB file from a previous run so each `pytest` invocation
# starts from a clean schema (test files also re-create tables per-test via
# the `clean_db` fixture in test_main_api.py, this is just belt-and-braces).
if os.path.exists(_TEST_DB_PATH):
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass

os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")
os.environ.setdefault("MERCHANT_API_TOKEN", "test_merchant_token")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
# Deliberately fake - nothing in this suite should ever make a real call
# that would use these. If a test starts failing with a real network error,
# that's a signal a mock is missing, not that these need to be "real".
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_fake_key_id")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "fake_key_secret")
os.environ.setdefault("GEMINI_API_KEY", "fake_gemini_key")
os.environ.setdefault("GEMINI_TEXT_MODEL", "gemini-3.6-flash")
os.environ.setdefault("GEMINI_VISION_MODEL", "gemini-3.6-flash")
