import hashlib
from datetime import datetime, timedelta

# These are still mocks (no real shipping/CRM system is wired up), but they're
# now deterministically VARIED per order/customer instead of one hardcoded
# value ("signed_by": "A. Arya", a fixed 2026-09-01 delivery date, etc.)
# returned for every single dispute regardless of what it's actually about.
# Same input -> same output every time (reproducible for testing), but
# different orders/customers now actually look different.
_CARRIERS = ["BlueDart", "Delhivery", "Ekart", "DTDC", "XpressBees"]
_SIGNEES = ["A. Arya", "R. Mehta", "S. Iyer", "P. Nair", "K. Rao", "V. Das"]


def _seed_for(key: str) -> int:
    """Deterministic integer seed derived from a string key."""
    return int(hashlib.sha256((key or "").encode()).hexdigest(), 16)


def get_shipping_data(order_id: str) -> str:
    """Mock API to fetch shipping tracking data."""
    seed = _seed_for(order_id)
    carrier = _CARRIERS[seed % len(_CARRIERS)]
    tracking_number = f"{carrier[:2].upper()}{seed % 900000000 + 100000000}"
    delivered_at = datetime.utcnow() - timedelta(days=(seed % 6) + 1)
    return str({
        "order_id": order_id,
        "status": "delivered",
        "carrier": carrier,
        "tracking_number": tracking_number,
        "delivered_at": delivered_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

def get_crm_logs(customer_identifier: str) -> str:
    """Mock API to fetch CRM logs and customer communications. Accepts a customer_id or email."""
    seed = _seed_for(customer_identifier)
    return str({
        "customer": customer_identifier,
        "account_age_days": 30 + (seed % 900),
        "previous_disputes": seed % 3,
        "recent_comms": "Customer contacted support describing the issue with this order."
    })

def get_delivery_confirmation(order_id: str) -> str:
    """Mock API to fetch proof of delivery signature/photos."""
    seed = _seed_for(order_id)
    signed_by = _SIGNEES[seed % len(_SIGNEES)]
    return str({
        "order_id": order_id,
        "signature_obtained": True,
        "signed_by": signed_by,
        "photo_proof_url": f"https://cdn.mockshipping.com/proof/{seed % 100000}.jpg"
    })

def get_customer_evidence(dispute_id: str) -> dict:
    """
    Mock API to fetch the evidence photo + claim text the customer attached to
    their dispute. In production this should call the Razorpay dispute evidence
    endpoint (or wherever the merchant's dispute-intake form stores uploads)
    instead of returning a fixture.

    Uses deterministic color-block placeholder images (not random stock
    photos) so the claim is visually obvious for a demo: this returns a
    BLACK block labeled as the item received, paired with get_reference_product_image()
    returning a NAVY BLUE block labeled as what was ordered - a real color
    mismatch the vision model can actually detect, instead of two unrelated
    random photos.
    """
    return {
        "dispute_id": dispute_id,
        "image_url": "https://dummyimage.com/600x600/1a1a1a/ffffff.png&text=Item+Received",
        "claim_text": "Item arrived in the wrong color — I ordered navy blue but received black.",
    }

def get_reference_product_image(order_id: str) -> dict:
    """
    Mock API to fetch the merchant's canonical/reference photo for the product
    on this order (e.g. from the product catalog or the delivery-confirmation
    photo). In production, wire this to the merchant's catalog/PIM or reuse the
    delivery confirmation photo_proof_url.

    Deliberately paired with get_customer_evidence() above: this is a NAVY
    BLUE block (what was actually ordered/shipped per the catalog), so the
    two images demonstrate a genuine, visually detectable color mismatch.
    """
    return {
        "order_id": order_id,
        "image_url": "https://dummyimage.com/600x600/1a3d7c/ffffff.png&text=Item+Ordered",
    }
