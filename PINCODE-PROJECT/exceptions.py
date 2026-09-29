from fastapi.responses import JSONResponse
from fastapi import Request


class PincodeNotFoundException(Exception):
    def __init__(self, pincode: str):
        self.pincode = pincode


class InvalidPincodeException(Exception):
    def __init__(self, pincode: str, reason: str = "Invalid pincode format"):
        self.pincode = pincode
        self.reason = reason

# Custom exception handler for PincodeNotFoundException


async def pincode_not_found_exception_handler(request: Request, exc: PincodeNotFoundException):
    return JSONResponse(

        status_code=404,
        content={
            "error": "pincode_not_found",
            "message": f"Pincode '{exc.pincode}' not found.",
            "pincode": exc.pincode
        },
    )

# Custom exception handler for InvalidPincodeException


async def invalid_pincode_exception_handler(request: Request, exc: InvalidPincodeException):
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_pincode",
            "message": f"Pincode '{exc.pincode}' is invalid. {exc.reason}",
            "pincode": exc.pincode
        },
    )
