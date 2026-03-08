import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from .audit import AuditLog
from .auth import limiter
from .factoryio_client import FactoryIOClient
from .historian import Historian
from .api.routes import router, init_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to every HTTP response.
    These tell browsers how to handle the content safely.

    X-Content-Type-Options  — don't guess the content type, trust what we say
    X-Frame-Options         — prevent this page being embedded in an iframe (clickjacking)
    Strict-Transport-Security — once you've seen HTTPS, never downgrade to HTTP
    Content-Security-Policy — only load resources from our own origin

    OWASP A05:2021 — Security Misconfiguration
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs startup logic before the server accepts requests,
    and shutdown logic after the last request is handled.
    This is the correct FastAPI pattern — no deprecated @app.on_event.
    """
    # Startup
    logger.info("Starting SCADA backend...")

    factoryio = FactoryIOClient()
    await factoryio.connect()

    historian = Historian(factoryio)
    await historian.start()

    audit = AuditLog()
    init_router(factoryio, historian, audit)

    logger.info("SCADA backend ready")
    yield

    # Shutdown — clean up in reverse order
    logger.info("Shutting down SCADA backend...")
    historian.disconnect()
    await factoryio.disconnect()


app = FastAPI(
    title="scada-sim API",
    description="Water treatment plant SCADA backend",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers on every response
app.add_middleware(SecurityHeadersMiddleware)

# CORS — only allow requests from the frontend origin
# Tighten this to the specific frontend URL in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:80", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type"],
)

app.include_router(router)


@app.get("/health")
async def health():
    """Simple health check — used by Docker to know if the container is ready."""
    return {"status": "ok"}
