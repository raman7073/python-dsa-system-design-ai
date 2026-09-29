from pydantic import BaseModel, field_validator


class PincodeRequest(BaseModel):
    pincode: str

    # pincode must be a 6-digit number
    @field_validator("pincode")
    @classmethod  # class method to validate pincode
    def validate_pincode(cls, value):
        if not value.isdigit() or len(value) != 6:
            raise ValueError("Pincode must be a 6-digit number.")
        return value


class LocationResponse(BaseModel):
    pincode: str
    city: str
    state: str
    district: str


class BulkRequest(BaseModel):
    pincodes: list[str]

    @field_validator("pincodes")
    @classmethod
    def validate_pincodes(cls, values):
        for pincode in values:
            if not pincode.isdigit() or len(pincode) != 6:
                raise ValueError(
                    f"Pincode '{pincode}' is invalid. Must be a 6-digit number.")
        return values


class BulkResponse(BaseModel):
    status: str = "success"
    found: int
    not_found: int
    results: list[LocationResponse] = []
    missing: list[str] = []
