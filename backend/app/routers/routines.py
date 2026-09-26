from fastapi import APIRouter

from app.db.models import Routine

router = APIRouter(prefix="/routines", tags=["routines"])


@router.get("")
async def list_routines(user_id: str):
    # TODO
    return []


@router.post("")
async def create_routine(routine: Routine):
    # TODO
    return routine


@router.delete("/{routine_id}")
async def delete_routine(routine_id: str):
    # TODO
    return {"deleted": routine_id}
