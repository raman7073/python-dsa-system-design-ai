from parking_spot import ParkingSpot


class ParkingFloor:
    def __init__(self, number: int, spots: list[ParkingSpot]) -> None:
        self.number = number
        self.spots = list(spots)
        spot_ids = [spot.spot_id for spot in self.spots]
        if len(spot_ids) != len(set(spot_ids)):
            raise ValueError("Spot IDs must be unique on a floor")

    def get_spot(self, spot_id: str) -> ParkingSpot | None:
        for spot in self.spots:
            if spot.spot_id == spot_id:
                return spot
        return None
