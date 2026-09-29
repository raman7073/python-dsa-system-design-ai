import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from model import TravelRequestModel
from services.currency import fetch_currency_rates
from services.weather import fetch_weather

# Step 1: Create a router. main.py registers it to expose POST /stream/.
router = APIRouter(
    prefix="/stream",
    tags=["Stream"]
)


def _event(name: str, data: object) -> str:
    # Step 2: Format an SSE message: event name, JSON data, then a blank line.
    # jsonable_encoder handles Pydantic models; json.dumps escapes newlines
    # inside values so they cannot accidentally split the SSE message.
    return f"event: {name}\ndata: {json.dumps(jsonable_encoder(data))}\n\n"


@router.post("/", response_class=StreamingResponse)
async def stream_travel_plan(travel: TravelRequestModel):
    """Stream weather/currency results, source errors, then done with success status.

    Accepts the same JSON body as /plan/. POST clients should consume the
    response stream using fetch or an HTTP client, rather than EventSource.
    After streaming starts, failures are SSE error events, not HTTP errors.
    """
    # Step 3: Validate dates before sending streaming response headers.
    # At this point we can still return a normal HTTP 400 response.
    if travel.start_date > travel.end_date:
        raise HTTPException(status_code=400, detail="Start Date cannot be greater than end date")
    if not 1 <= (travel.end_date - travel.start_date).days + 1 <= 14:
        raise HTTPException(
            status_code=400,
            detail="Trips must contain between 1 and 14 days, including both dates.",
        )

    # Step 4: Use an async generator to produce the response incrementally.
    # Each yield supplies another chunk while the HTTP connection stays open.
    async def events():
        # Step 5: Schedule both provider calls concurrently. The mapping lets
        # us identify which service produced each completed task's result.
        tasks = {
            asyncio.create_task(fetch_weather(
                destination=travel.destination,
                start_date=travel.start_date,
                end_date=travel.end_date,
            )): "weather",
            asyncio.create_task(fetch_currency_rates(
                base_currency=travel.base_currency,
            )): "currency",
        }
        pending = set(tasks)
        success = True
        try:
            while pending:
                # Step 6: Wait for the next result, not for both services.
                # Unlike gather, FIRST_COMPLETED lets us stream a fast result
                # while the slower call continues. Multiple tasks may be ready.
                completed, pending = await asyncio.wait(
                    pending, timeout=15, return_when=asyncio.FIRST_COMPLETED
                )
                if not completed:
                    # Step 7: If nothing finishes for 15 seconds, send an SSE
                    # comment as a heartbeat. This does not cancel pending calls.
                    yield ": keep-alive\n\n"
                for task in completed:
                    source = tasks[task]
                    try:
                        # Step 8: Read the completed task. result() either
                        # returns its value or raises the service's exception.
                        result = task.result()
                    except (ValueError, RuntimeError) as exc:
                        # Headers are already sent, so report failures as SSE
                        # events. status_code here is data, not the HTTP status.
                        # The other service can still deliver a useful result.
                        success = False
                        yield _event("error", {
                            "source": source,
                            "status_code": 400 if isinstance(exc, ValueError) else 502,
                            "detail": str(exc),
                        })
                    except Exception:
                        # Keep unexpected exception details out of the response.
                        success = False
                        yield _event("error", {
                            "source": source, "status_code": 500,
                            "detail": "Unable to retrieve travel data",
                        })
                    else:
                        # Send a named weather/currency event as soon as ready.
                        yield _event(source, result)
            # Step 9: Tell the client that all services have finished.
            # success is false if any service failed; then the stream ends.
            yield _event("done", {"success": success})
        finally:
            # Step 10: Clean up when the generator finishes, closes, or is
            # cancelled. Cancel unfinished calls and collect all task outcomes.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    # Step 11: Hand the generator to FastAPI; it will consume and stream it.
    # text/event-stream identifies SSE. These headers discourage caching and
    # request that compatible proxies (such as nginx) avoid buffering chunks.
    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
