from vehicle import Vehicle


class ParkingSpot:
    # Each vehicle kind lists the spot types it can use.
    ALLOWED_SPOTS = {
        "motorcycle": ("compact", "regular", "large"),
        "car": ("regular", "large"),
        "truck": ("large",),
    }

    def __init__(self, spot_id: str, spot_type: str) -> None:
        if not spot_id:
            raise ValueError("A spot needs an ID")
        if spot_type not in ("compact", "regular", "large"):
            raise ValueError("Unknown spot type")
        self.spot_id = spot_id
        self.spot_type = spot_type
        self.vehicle: Vehicle | None = None

    def is_occupied(self) -> bool:
        return self.vehicle is not None

    def can_fit(self, vehicle: Vehicle) -> bool:
        allowed = self.ALLOWED_SPOTS.get(vehicle.kind, ())
        return self.spot_type in allowed

    def park(self, vehicle: Vehicle) -> None:
        if self.is_occupied():
            raise ValueError("Spot is already occupied")
        if not self.can_fit(vehicle):
            raise ValueError("Vehicle cannot fit in this spot")
        self.vehicle = vehicle

    def remove_vehicle(self) -> None:
        if not self.is_occupied():
            raise ValueError("Spot is already empty")
        self.vehicle = None
