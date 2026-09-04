"""
Exercises the self-service order + claim flow against a running backend
(`docker compose up`, or `uvicorn app.main:app` from backend/) and proves the
ownership check actually denies a cross-user claim attempt.

What this CAN test headlessly:
  - signup
  - real Razorpay order creation (Orders API - needs real test-mode keys)
  - the security property this feature is about: user B is denied (403)
    when trying to claim against user A's order.
  - the "must be paid first" guard (400 on an unpaid order).

What this CANNOT test headlessly:
  - a full happy-path refund. Completing a real payment requires driving
    Razorpay's Checkout in an actual browser with a Razorpay test card -
    there is no plain server-side "simulate a successful payment" endpoint.
    To see the full approve_refund -> real refund path, create an order via
    this script (or the app), pay it in a browser using Razorpay's test
    card (4111 1111 1111 1111, any future expiry/CVV), POST the resulting
    razorpay_order_id/payment_id/signature to /orders/{id}/verify-payment,
    then POST /disputes/claim.

Run with: python test_claim_flow.py
(from the backend/ directory, against a running backend + real Razorpay
Test Mode keys in the environment.)
"""

import time
import httpx

BASE_URL = "http://localhost:8000"


def signup(email: str) -> dict:
    resp = httpx.post(f"{BASE_URL}/auth/signup", json={"email": email})
    if resp.status_code == 409:
        raise SystemExit(
            f"'{email}' already exists from a previous run - use a fresh email "
            f"(e.g. add a timestamp) or clear the users table and retry."
        )
    resp.raise_for_status()
    return resp.json()


def main():
    stamp = int(time.time())
    user_a = signup(f"alice+{stamp}@example.com")
    user_b = signup(f"bob+{stamp}@example.com")
    print(f"User A: {user_a['user_id']}")
    print(f"User B: {user_b['user_id']}")

    headers_a = {"Authorization": f"Bearer {user_a['api_token']}"}
    headers_b = {"Authorization": f"Bearer {user_b['api_token']}"}

    # --- User A creates an order (real Razorpay Orders API call) ---
    resp = httpx.post(f"{BASE_URL}/orders", json={"amount": 49900, "currency": "INR"}, headers=headers_a)
    if resp.status_code != 200:
        print(f"\nOrder creation failed ({resp.status_code}): {resp.text}")
        print("This usually means RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET aren't set on the backend.")
        return
    order = resp.json()
    order_id = order["order_id"]
    print(f"\nOrder created by User A: {order_id} (amount={order['amount']} {order['currency']})")

    # --- User B tries to claim against User A's order: must be denied ---
    resp = httpx.post(
        f"{BASE_URL}/disputes/claim",
        json={"order_id": order_id, "reason_code": "not_as_described", "claim_details": "Not my order, testing denial."},
        headers=headers_b,
    )
    print(f"\nUser B claiming User A's order -> {resp.status_code} {resp.json()}")
    assert resp.status_code == 403, f"SECURITY BUG: expected 403, got {resp.status_code}"
    print("OK: cross-user claim correctly denied with 403.")

    # --- User A tries to claim before paying: must be denied (order not paid yet) ---
    resp = httpx.post(
        f"{BASE_URL}/disputes/claim",
        json={"order_id": order_id, "reason_code": "not_as_described", "claim_details": "Testing pre-payment guard."},
        headers=headers_a,
    )
    print(f"\nUser A claiming their own UNPAID order -> {resp.status_code} {resp.json()}")
    assert resp.status_code == 400, f"Expected 400 (not paid), got {resp.status_code}"
    print("OK: claim on an unpaid order correctly rejected with 400.")

    print(
        "\nTo see the full flow (claim on a PAID order -> AI adjudication -> real refund), "
        "pay this order in a browser via Razorpay Checkout using a test card, POST the "
        "resulting fields to /orders/{order_id}/verify-payment, then retry the claim as User A."
    )


if __name__ == "__main__":
    main()
