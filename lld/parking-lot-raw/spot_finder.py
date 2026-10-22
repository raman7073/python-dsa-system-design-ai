from parking_floor import ParkingFloor
from parking_spot import ParkingSpot
from vehicle import Vehicle


class FirstAvailableSpot:
    def find(
        self, floors: list[ParkingFloor], vehicle: Vehicle
    ) -> tuple[ParkingFloor, ParkingSpot] | None:
        for floor in floors:
            for spot in floor.spots:
                if not spot.is_occupied() and spot.can_fit(vehicle):
                    return floor, spot
        return None
