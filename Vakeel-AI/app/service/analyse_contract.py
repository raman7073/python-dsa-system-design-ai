import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import httpx
from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from config import GEMINI_API_KEY, GEMINI_MODEL
from database import analysis_collection, contracts_collection
from .prompt import CONTRACT_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"
    ":generateContent"
)


class AnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Party(AnalysisItem):
    name: str | None
    role: str | None


class KeyTerms(AnalysisItem):
    effective_date: str | None
    expiration_date: str | None
    duration: str | None
    payment_terms: str | None
    renewal: str | None
    termination: str | None
    confidentiality: str | None
    intellectual_property: str | None
    liability: str | None
    indemnity: str | None
    governing_law: str | None
    dispute_resolution: str | None


class Obligation(AnalysisItem):
    party: str | None
    description: str
    deadline: str | None
    clause_reference: str | None
    evidence: str


class Risk(AnalysisItem):
    title: str
    severity: Literal["low", "medium", "high"]
    affected_party: str | None
    clause_reference: str | None
    evidence: str | None
    explanation: str
    recommendation: str


class UnclearTerm(AnalysisItem):
    term: str
    explanation: str


class ContractAnalysis(AnalysisItem):
    contract_type: str | None
    summary: str
    parties: list[Party]
    key_terms: KeyTerms
    obligations: list[Obligation]
    risks: list[Risk]
    missing_or_unclear_terms: list[UnclearTerm]
    overall_risk_level: Literal["low", "medium", "high", "unknown"]
    overall_risk_explanation: str
    questions_for_review: list[str]
    review_limitations: list[str]


async def _generate_analysis(text_content: str) -> dict:
    payload = {
        "contents": [{"role": "user", "parts": [{
            "text": CONTRACT_ANALYSIS_PROMPT.format(contract_text=text_content)
        }]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": ContractAnalysis.model_json_schema(),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = await client.post(
                GEMINI_URL, headers={"x-goog-api-key": GEMINI_API_KEY}, json=payload
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(
            504, "AI analysis timed out. Please try again.") from None
    except httpx.HTTPStatusError as exc:
        logger.warning("Gemini request failed with HTTP %s", exc.response.status_code)
        if exc.response.status_code == 429:
            raise HTTPException(
                503, "AI service quota exceeded. Please try again later.") from None
        if exc.response.status_code in (500, 502, 503, 504):
            raise HTTPException(
                503, "AI service is temporarily unavailable or busy. Please try again later.") from None
        if exc.response.status_code in (401, 403):
            raise HTTPException(
                502, "AI service authentication or permission failed. Check the configured API key.") from None
        if exc.response.status_code == 404:
            raise HTTPException(
                502, "Configured AI model was not found. Check GEMINI_MODEL.") from None
        raise HTTPException(
            502, "AI service rejected the request payload. Check the input and generation configuration.") from None
    except httpx.RequestError:
        raise HTTPException(502, "Unable to reach the AI service.") from None

    try:
        candidate = response.json()["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            raise ValueError("Incomplete or blocked response")
        text = "".join(
            part.get("text", "") for part in candidate["content"]["parts"]
            if not part.get("thought", False)
        )
        return ContractAnalysis.model_validate_json(text).model_dump(mode="json")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError):
        raise HTTPException(
            502, "AI service returned an incomplete or invalid analysis.") from None


async def analyze_contract(contract_id: str, text_content: str) -> dict:
    """Analyze the full contract using Gemini, persist it, and return JSON-safe data."""
    if not GEMINI_API_KEY:
        raise HTTPException(500, "AI API key is not configured")
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(400, "Invalid contract ID")
    if not text_content or not text_content.strip():
        raise HTTPException(400, "Contract has no text content to analyse")

    query = {"_id": ObjectId(contract_id)}
    started = False
    try:
        updated = await run_in_threadpool(
            contracts_collection.update_one, query, {
                "$set": {"analysis_status": "in_progress"}}
        )
        if not updated.matched_count:
            raise HTTPException(404, "Contract not found")
        started = True
        analysis = await _generate_analysis(text_content)
        document = {
            "analysis_id": uuid4().hex,
            "contract_id": str(query["_id"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": GEMINI_MODEL,
            "analysis": analysis,
        }
        # PyMongo adds an ObjectId to the inserted dictionary; keep it out of the response.
        await run_in_threadpool(analysis_collection.insert_one, document.copy())
        await run_in_threadpool(
            contracts_collection.update_one, query, {
                "$set": {"analysis_status": "completed"}}
        )
        return document
    except (HTTPException, PyMongoError) as exc:
        if started:
            try:
                await run_in_threadpool(
                    contracts_collection.update_one, query, {
                        "$set": {"analysis_status": "failed"}}
                )
            except PyMongoError:
                logger.warning("Could not mark contract analysis as failed")
        if isinstance(exc, PyMongoError):
            raise HTTPException(
                503, "Database unavailable while saving analysis.") from None
        raise
