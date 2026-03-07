import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import verify_api_key, limiter
from ..factoryio_client import FactoryIOClient
from ..historian import Historian

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Set by main.py during startup — routes access these via module-level refs
_factoryio: FactoryIOClient = None
_historian: Historian = None


def init_router(factoryio: FactoryIOClient, historian: Historian):
    """Called once at startup to give routes access to the shared clients."""
    global _factoryio, _historian
    _factoryio = factoryio
    _historian = historian


# ── Request models ─────────────────────────────────────────────────────────────
# Pydantic validates incoming JSON automatically — if the payload doesn't match,
# FastAPI returns a 422 before our code even runs (OWASP A03 — Injection)

class ValveCommand(BaseModel):
    open: bool


# ── Read endpoints (public) ────────────────────────────────────────────────────

@router.get("/state")
@limiter.limit("60/minute")
async def get_state(request: Request):
    """
    Current plant state — live sensor values, valve states, alarms.
    Public endpoint: operators need to monitor without friction.
    Documented as accepted risk I-01 in threat model.
    """
    state = await _factoryio.read()
    return asdict(state)


@router.get("/alarms")
async def get_alarms():
    """Active alarms only — read-only, public."""
    return [asdict(a) for a in _factoryio.state.alarms]


@router.get("/history/{field}")
async def get_history(field: str, minutes: int = 60):
    """
    Historical trend data for a given field over the last N minutes.
    Used by the HMI trend charts.

    Field is validated against an allowlist to prevent injection via
    the URL parameter (OWASP A03 — Injection).
    """
    allowed_fields = {"tank_level", "flow_rate", "setpoint", "alarm_count"}
    if field not in allowed_fields:
        raise HTTPException(status_code=400, detail=f"Unknown field: {field}")
    if not 1 <= minutes <= 1440:
        raise HTTPException(status_code=400, detail="minutes must be between 1 and 1440")

    try:
        data = _historian.query(field, minutes)
        return {"field": field, "minutes": minutes, "data": data}
    except Exception as exc:
        logger.error(f"History query failed: {exc}")
        raise HTTPException(status_code=500, detail="Historian query failed")


# ── Control endpoints (require API key) ────────────────────────────────────────

@router.post("/control/fill-valve", dependencies=[Depends(verify_api_key)])
async def control_fill_valve(cmd: ValveCommand, request: Request):
    """
    Open or close the fill valve.
    Requires API key — only authorised operators can command actuators.
    OWASP API2:2023 — Broken Authentication
    """
    logger.info(f"CONTROL fill_valve open={cmd.open} from={request.client.host}")
    await _factoryio.cmd_fill_valve(cmd.open)
    return {"fill_valve": cmd.open}


@router.post("/control/discharge-valve", dependencies=[Depends(verify_api_key)])
async def control_discharge_valve(cmd: ValveCommand, request: Request):
    """
    Open or close the discharge valve.
    Requires API key — only authorised operators can command actuators.
    """
    logger.info(f"CONTROL discharge_valve open={cmd.open} from={request.client.host}")
    await _factoryio.cmd_discharge_valve(cmd.open)
    return {"discharge_valve": cmd.open}
