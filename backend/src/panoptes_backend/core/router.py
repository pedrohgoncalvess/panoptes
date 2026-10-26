from fastapi import APIRouter, Request
from panoptes_database.session import unit_of_work
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live():
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request):
    async with unit_of_work(request.app.state.sessions) as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}
