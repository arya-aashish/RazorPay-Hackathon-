import hmac
import hashlib
import json
import time
import httpx
import os
from dotenv import load_dotenv

# Load the environment variables from the .env file
load_dotenv(dotenv_path="../.env")

# 1. Setup the secret dynamically
secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

if not secret:
    print("Error: RAZORPAY_WEBHOOK_SECRET is not set in the environment.")
    exit(1)

# Realistic nested payload matching Razorpay's actual dispute webhook shape,
# with a reason_code that triggers the visual-evidence pipeline (see
# reason_codes.yaml: 'not_as_described' -> visual_evidence_comparison).
# This exercises reason-code routing + the vision pipeline + deadline
# capture, not just the webhook-receipt path.
payload = {
    "event": "payment.dispute.created",
    "payload": {
        "dispute": {
            "entity": {
                "id": f"disp_test_{int(time.time())}",
                "reason_code": "not_as_described",
                "customer_id": "test-customer@example.com",
                "order_id": "order_demo_001",
                "claim_details": "Item arrived in the wrong color — I ordered navy blue but received black.",
                "evidence_image_url": "https://dummyimage.com/600x600/1a1a1a/ffffff.png&text=Item+Received",
                # respond_by is a unix timestamp per Razorpay's dispute entity;
                # set 3 days out so deadline capture has something real to show.
                "respond_by": int(time.time()) + (3 * 24 * 60 * 60),
            }
        }
    },
}

# 2. Hash the exact raw bytes
raw_body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

# 3. Send the request
response = httpx.post(
    "http://localhost:8000/webhook",
    content=raw_body,
    headers={"X-Razorpay-Signature": signature}
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
print()
print(f"Dispute ID sent: {payload['payload']['dispute']['entity']['id']}")
print("Poll GET /disputes/<id> above in a few seconds to see the agent pipeline's decision")
print("(background task takes a few seconds to run - the webhook response above")
print("only confirms receipt, not the final decision).")
