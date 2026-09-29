import asyncio

from fastapi import APIRouter, HTTPException
from model import TravelRequestModel
from services.weather import fetch_weather
from services.currency import fetch_currency_rates

router = APIRouter(
    prefix="/plan",
    tags=["Travel Plan"]
)


@router.post("/")
async def create_travel_plan(
    travel_request: TravelRequestModel,

):
    """Aggregate weather and currency data into a single travel plan."""
    if travel_request.start_date > travel_request.end_date:
        raise HTTPException(
            status_code=400, detail="Start Date cannot be greater than end date")
    trip_days = (travel_request.end_date - travel_request.start_date).days + 1
    if trip_days < 1 or trip_days > 14:
        raise HTTPException(
            status_code=400, detail="Trips must contain between 1 and 14 days, including both dates.")

    try:
        weather_data, currency_data = await asyncio.gather(
            fetch_weather(
                destination=travel_request.destination,
                start_date=travel_request.start_date,
                end_date=travel_request.end_date
            ),
            fetch_currency_rates(
                base_currency=travel_request.base_currency
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None

    return {
        "message": "Travel plan created successfully",
        "weather_data": weather_data,
        "currency_data": currency_data
    }
