import hmac
import hashlib
import logging
from fastapi import Request, HTTPException, Header
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("chargeback_responder")

# We will store this in the .env file shortly
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "dummy_secret_for_now")

async def verify_razorpay_signature(request: Request, x_razorpay_signature: str = Header(None)):
    if not x_razorpay_signature:
        logger.warning("Webhook rejected: missing X-Razorpay-Signature header.")
        raise HTTPException(status_code=401, detail="Missing Razorpay signature header")
    
    # We need the raw body to calculate the HMAC
    body = await request.body()
    
    # Calculate the expected signature
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(), 
        body, 
        hashlib.sha256
    ).hexdigest()
    
    # Compare securely to prevent timing attacks
    if not hmac.compare_digest(expected_signature, x_razorpay_signature):
        logger.warning("Webhook rejected: invalid signature.")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    return True