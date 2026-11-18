import threading
from typing import Dict, List, Optional

from parking_lot_v5.parking_spot import ParkingSpot
from shared.spot_allocation_strategy import SpotAllocationStrategy
from shared.vehicle import Vehicle


class FloorManager:
    """One lock per floor: gates parking on different floors never wait for each other."""

    def __init__(
        self,
        floor_id: int,
        spots: List[ParkingSpot],
        strategy: SpotAllocationStrategy,
    ) -> None:
        self._floor_id: int = floor_id
        self._spots: List[ParkingSpot] = list(spots)
        self._spots_by_id: Dict[str, ParkingSpot] = {spot.id: spot for spot in self._spots}
        self._strategy: SpotAllocationStrategy = strategy
        self._lock: threading.Lock = threading.Lock()

    def try_allocate(self, v: Vehicle) -> Optional[ParkingSpot]:
        """Find AND claim inside one critical section, so two gates can't get the same spot."""
        with self._lock:
            spot = self._strategy.find_spot(v, self._spots)
            if spot is not None:
                spot.occupy()
            return spot

    def release(self, spot_id: str) -> None:
        with self._lock:
            self._spots_by_id[spot_id].free()

    @property
    def floor_id(self) -> int:
        return self._floor_id