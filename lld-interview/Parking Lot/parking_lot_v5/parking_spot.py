from shared.illegal_state_exception import IllegalStateError
from shared.spot_size import SpotSize
from shared.spot_status import SpotStatus
from shared.vehicle import Vehicle


class ParkingSpot:
    """Not thread-safe by itself: only FloorManager touches it, always under the floor lock."""

    def __init__(self, spot_id: str, floor_id: int, size: SpotSize, distance: int) -> None:
        self._id: str = spot_id
        self._floor_id: int = floor_id
        self._size: SpotSize = size
        self._distance: int = distance
        self._status: SpotStatus = SpotStatus.FREE

    def can_fit(self, v: Vehicle) -> bool:
        return self._status == SpotStatus.FREE and self._size.can_hold(v.type.required_size)

    def occupy(self) -> None:
        if self._status != SpotStatus.FREE:
            raise IllegalStateError(f"{self._id} is {self._status}")
        self._status = SpotStatus.OCCUPIED

    def free(self) -> None:
        if self._status != SpotStatus.OCCUPIED:
            raise IllegalStateError(f"{self._id} is {self._status}")
        self._status = SpotStatus.FREE

    @property
    def id(self) -> str:
        return self._id

    @property
    def floor_id(self) -> int:
        return self._floor_id

    @property
    def size(self) -> SpotSize:
        return self._size

    @property
    def distance(self) -> int:
        return self._distance

    @property
    def status(self) -> SpotStatus:
        return self._status