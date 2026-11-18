from abc import ABC, abstractmethod
from datetime import datetime

from shared.charge import Charge
from shared.vehicle_type import VehicleType


class PricingStrategy(ABC):
    @abstractmethod
    def parking_charge(self, vehicle_type: VehicleType, entry: datetime, exit_time: datetime) -> Charge:
        pass