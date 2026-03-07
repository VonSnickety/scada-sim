import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings

# Rate limiter — keyed by client IP address
limiter = Limiter(key_func=get_remote_address)

# Expects the API key in an "X-API-Key" request header
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """
    Validate the API key on control endpoints.

    Uses secrets.compare_digest instead of == to prevent timing attacks —
    a naive string comparison returns faster when early characters don't match,
    which lets an attacker measure response times to guess the key one
    character at a time. compare_digest always takes the same amount of time.

    OWASP A07:2021 — Identification and Authentication Failures
    Essential Eight — Restrict Administrative Privileges
    """
    if not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
