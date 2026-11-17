"""A2A 入站状态面板（登录即可，只读 + ping）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..hermes import a2a_inbound
from ..security import CurrentUser

router = APIRouter(prefix="/api/a2a/inbound", tags=["a2a-inbound"])


@router.get("")
async def get_inbound(_: CurrentUser) -> dict:
    """A2A 入站配置与健康状态（只读）。"""
    try:
        return await a2a_inbound.inbound_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/ping")
async def ping(_: CurrentUser) -> dict:
    return await a2a_inbound.ping_inbound()
