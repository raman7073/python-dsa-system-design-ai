from enum import Enum
from shared.spot_size import SpotSize

class VehicleType(Enum):
    BIKE = SpotSize.SMALL
    CAR = SpotSize.MEDIUM
    TRUCK = SpotSize.LARGE

    def __init__(self, required_size: SpotSize):
        self._required_size = required_size

    @property
    def required_size(self) -> SpotSize:
        return self._required_size
