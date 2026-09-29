from fastapi import APIRouter, HTTPException, Depends
from auth import get_current_user
from config import GEMINI_API_KEY
from database import contracts_collection, analysis_collection
from bson import ObjectId
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool
from service.analyse_contract import analyze_contract

router = APIRouter(
    prefix='/analysis',
    tags=["analysis"], dependencies=[Depends(get_current_user)]
)


@router.post("/analyze/{contract_id}")
async def analyse_contract(contract_id: str, user: dict = Depends(get_current_user)):
    """
    Analyze a contract using AI and return insights
    """

    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500, detail="AI API key is not configured")
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")
    try:
        doc = await run_in_threadpool(
            contracts_collection.find_one, {"_id": ObjectId(contract_id), "owner_id": user["id"]}
        )
    except PyMongoError:
        raise HTTPException(
            status_code=503, detail="Database unavailable") from None
    if doc is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    if not doc.get("text_content"):
        raise HTTPException(
            status_code=400, detail="Contract has no text content to analyse")

    result = await analyze_contract(contract_id, doc["text_content"])
    return {"message": "Contract analysed successfully", "analysis": result}


@router.get("/{analysis_id}")
async def get_analysis(analysis_id: str, user: dict = Depends(get_current_user)):
    """Retrieve a saved result by its analysis_id, not its contract_id."""
    try:
        doc = await run_in_threadpool(
            analysis_collection.find_one, {"analysis_id": analysis_id}, {"_id": 0}
        )
        if doc is not None:
            contract_id = doc.get("contract_id", "")
            owner = None
            if ObjectId.is_valid(contract_id):
                owner = await run_in_threadpool(
                    contracts_collection.find_one,
                    {"_id": ObjectId(contract_id), "owner_id": user["id"]},
                    {"_id": 1},
                )
            if owner is None:
                doc = None
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    if doc is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"analysis": doc}
