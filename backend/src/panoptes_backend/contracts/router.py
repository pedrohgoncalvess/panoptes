from fastapi import APIRouter, HTTPException
from panoptes_contracts import CONTRACTS

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.get("")
async def list_contracts():
    return {"version": "1.2", "contracts": sorted(CONTRACTS)}


@router.get("/{name}")
async def read_contract(name: str):
    model = CONTRACTS.get(name)
    if model is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return model.model_json_schema()
