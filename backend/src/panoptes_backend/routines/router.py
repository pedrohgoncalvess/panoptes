from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ..catalog.router import session_dependency
from . import repository, services
from .models import RoutineAdvance, RoutineCreate, RoutineUpdate

router = APIRouter(prefix="/routines", tags=["routines"])


@router.post("", status_code=201)
async def create(value: RoutineCreate, session=Depends(session_dependency)):
    return await services.create(session, value)


@router.get("")
async def list_routines(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    scheduled: bool = False,
    session=Depends(session_dependency),
):
    return await repository.list_routines(session, limit, offset, scheduled)


@router.post("/{routine_id}/advance")
async def advance(
    routine_id: UUID, value: RoutineAdvance, session=Depends(session_dependency)
):
    return await services.advance(session, routine_id, value)


@router.get("/{routine_id}")
async def read(routine_id: UUID, session=Depends(session_dependency)):
    return await services.read(session, routine_id)


@router.put("/{routine_id}")
async def update(
    routine_id: UUID, value: RoutineUpdate, session=Depends(session_dependency)
):
    return await services.update(session, routine_id, value)


@router.delete("/{routine_id}", status_code=204)
async def delete(routine_id: UUID, session=Depends(session_dependency)):
    await services.delete(session, routine_id)
