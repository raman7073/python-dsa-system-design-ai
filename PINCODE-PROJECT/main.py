from fastapi import FastAPI
from exceptions import (
    PincodeNotFoundException,
    pincode_not_found_exception_handler,
    InvalidPincodeException,
    invalid_pincode_exception_handler,
)
from models import BulkRequest, BulkResponse, LocationResponse

app = FastAPI(
    title="Pincode API",
    description="This is a simple API to get the details of a pincode.",
)

# Register custom exception handlers
app.add_exception_handler(PincodeNotFoundException,
                          pincode_not_found_exception_handler)
app.add_exception_handler(InvalidPincodeException,
                          invalid_pincode_exception_handler)


@app.get("/")
async def read_root():
    return {"message": "Welcome to the Pincode API"}


@app.get("/pincode/{pincode}", response_model=LocationResponse)
async def lookup_pincode(pincode: str):
    # Validate pincode format
    if not pincode.isdigit() or len(pincode) != 6:
        raise InvalidPincodeException(
            pincode, reason="Pincode must be a 6-digit number.")

    # Lookup pincode in the database
    from data import pincode_db
    if pincode not in pincode_db:
        raise PincodeNotFoundException(pincode)

    location = pincode_db[pincode]
    return LocationResponse(
        pincode=pincode,
        city=location["city"],
        state=location["state"],
        district=location.get("district", "N/A")
    )


@app.post("/bulk_lookup", response_model=BulkResponse)
async def bulk_lookup(request: BulkRequest):
    from data import pincode_db
    found = 0
    not_found = 0
    results = []
    missing = []

    for pincode in request.pincodes:
        if pincode in pincode_db:
            location = pincode_db[pincode]
            results.append(LocationResponse(
                pincode=pincode,
                city=location["city"],
                state=location["state"],
                district=location.get("district", "N/A")
            ))
            found += 1
        else:
            missing.append(pincode)
            not_found += 1

    return BulkResponse(
        found=found,
        not_found=not_found,
        results=results,
        missing=missing
    )
