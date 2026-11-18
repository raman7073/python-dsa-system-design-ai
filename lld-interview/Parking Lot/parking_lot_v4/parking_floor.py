from typing import Dict, List

from parking_lot_v4.parking_spot import ParkingSpot
from shared.spot_size import SpotSize
from shared.spot_status import SpotStatus


class ParkingFloor:
    """
    A floor is a real domain concept: drivers are sent to it, boards show its counts,
    and it can be closed. It has NO lock of its own: ParkingLot's lot lock guards it.
    """

    def __init__(self, floor_id: int, spots: List[ParkingSpot]) -> None:
        for s in spots:
            if s.floor_id != floor_id:
                raise ValueError(f"{s.id} is not on floor {floor_id}")
        self._floor_id: int = floor_id
        self._spots: List[ParkingSpot] = list(spots)
        self._open: bool = True

    def free_counts(self) -> Dict[SpotSize, int]:
        counts: Dict[SpotSize, int] = {size: 0 for size in SpotSize}
        for s in self._spots:
            if s.status == SpotStatus.FREE:
                counts[s.size] += 1
        return counts

    @property
    def floor_id(self) -> int:
        return self._floor_id

    @property
    def spots(self) -> List[ParkingSpot]:
        return list(self._spots)

    @property
    def is_open(self) -> bool:
        return self._open

    @is_open.setter
    def is_open(self, open_status: bool) -> None:
        self._open = open_status