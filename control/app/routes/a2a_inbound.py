"""管理员：A2A 入站状态面板。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..hermes import a2a_inbound
from ..security import CurrentAdmin

router = APIRouter(prefix="/api/admin/a2a-inbound", tags=["admin:a2a-inbound"])


@router.get("")
async def get_inbound(_: CurrentAdmin) -> dict:
    """A2A 入站配置与健康状态（只读）。"""
    try:
        return await a2a_inbound.inbound_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/ping")
async def ping(_: CurrentAdmin) -> dict:
    return await a2a_inbound.ping_inbound()
