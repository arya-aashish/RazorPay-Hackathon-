import logging
from datetime import datetime

from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

logger = logging.getLogger("chargeback_responder")


def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Minimal bearer-token auth dependency. Each user is issued an opaque
    api_token at signup (POST /auth/signup). Every order-creation and
    claim-filing endpoint depends on this to resolve "who is calling" -
    the caller can never just assert their own user_id in a request body.

    This is what makes the order-ownership check on POST /disputes/claim
    a real security boundary rather than a check that anyone could bypass
    just by knowing/guessing someone else's order_id: filing a claim also
    requires proving you're the token-holder who created that order.

    Tokens have a server-enforced expiry. This remains deliberately minimal:
    production should add a real login/refresh-token or magic-link flow and
    explicit server-side revocation rather than using signup as identity proof.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header. Expected: Bearer <api_token>",
        )

    token = authorization.split(" ", 1)[1].strip()
    user = db.query(User).filter(User.api_token == token).first()
    if not user:
        logger.warning("Auth rejected: unknown API token presented.")
        raise HTTPException(status_code=401, detail="Invalid API token")

    # Rows created before token expiry was introduced are treated as expired
    # rather than granting an indefinite legacy session.
    if not user.token_expires_at or user.token_expires_at <= datetime.utcnow():
        logger.info("Auth rejected: expired customer API token.")
        raise HTTPException(status_code=401, detail="API token has expired. Please sign in again.")

    return user
