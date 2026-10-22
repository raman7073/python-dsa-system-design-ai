from parking_spot import ParkingSpot, ParkingSpotType
from vehicle import Vehicle, VehicleType


class ParkingFloor:
    def __init__(self, floor_id: str, spots: list[ParkingSpot]) -> None:
        if not floor_id:
            raise ValueError("A floor needs an ID")

        self.floor_id: str = floor_id
        self.spots: list[ParkingSpot] = []
        self._spots_by_type: dict[str, list[ParkingSpot]] = {}
        self._spots_by_id: dict[str, ParkingSpot] = {}

        for spot in spots:
            if spot.floor_id != floor_id:
                raise ValueError("Spot belongs to another floor")
            if spot.spot_id in self._spots_by_id:
                raise ValueError("Spot IDs must be unique on a floor")

            self._spots_by_id[spot.spot_id] = spot
            self.spots.append(spot)
            self._spots_by_type.setdefault(spot.spot_type, []).append(spot)

    def get_floor_id(self) -> str:
        return self.floor_id

    def get_spot(self, spot_id: str) -> ParkingSpot | None:
        return self._spots_by_id.get(spot_id)

    def allocate_spot(self, vehicle: Vehicle) -> ParkingSpot | None:
        vehicle_type = vehicle.get_vehicle_type()

        # Try the smallest suitable spot first to leave large spots for trucks and vans.
        if vehicle_type == VehicleType.CAR:
            spot_types = [ParkingSpotType.COMPACT, ParkingSpotType.LARGE]
            if vehicle.accessible:
                spot_types.insert(0, ParkingSpotType.DISABLED)
        elif vehicle_type in (VehicleType.TRUCK, VehicleType.VAN):
            spot_types = [ParkingSpotType.LARGE]
        elif vehicle_type == VehicleType.ELECTRIC_CAR:
            spot_types = [ParkingSpotType.ELECTRIC_CAR]
        elif vehicle_type == VehicleType.MOTORCYCLE:
            spot_types = [ParkingSpotType.MOTORCYCLE]
        else:
            # A new vehicle type can use a newly added spot without a floor branch.
            spot_types = list(self._spots_by_type)

        for spot_type in spot_types:
            for spot in self._spots_by_type.get(spot_type, []):
                if spot.is_free() and spot.can_fit(vehicle):
                    spot.park(vehicle)
                    return spot
        return None

    def release_spot(self, spot_id: str) -> None:
        spot = self.get_spot(spot_id)
        if spot is None:
            raise ValueError("Unknown spot ID")
        spot.vacate()
