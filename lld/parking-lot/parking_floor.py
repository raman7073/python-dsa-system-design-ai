from dataclasses import dataclass
from typing import List, Optional

from parking_spot import ParkingSpot


@dataclass
class ParkingFloor:
    floor_number: int
    spots: List[ParkingSpot]

    def __post_init__(self) -> None:
        spot_ids = [spot.spot_id for spot in self.spots]
        if len(spot_ids) != len(set(spot_ids)):
            raise ValueError("Spot IDs must be unique within a floor")

    def get_spot(self, spot_id: str) -> Optional[ParkingSpot]:
        return next((spot for spot in self.spots if spot.spot_id == spot_id), None)
