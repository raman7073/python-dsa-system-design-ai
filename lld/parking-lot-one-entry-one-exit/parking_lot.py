from model.entry_panel import EntryPanel
from model.exit_panel import ExitPanel
from model.hourly_cost import HourlyCost
from model.parking_floor import ParkingFloor
from model.parking_spot import ParkingSpot
from model.parking_ticket import ParkingTicket
from context.payment_context import PaymentContext
from strategy.pricing import PricingStrategy, TimeBasedPricingStrategy
from model.vehicle import Vehicle


class ParkingLot:
    """Own the floors and the one entry panel and one exit panel."""

    def __init__(
        self,
        floors: list[ParkingFloor],
        pricing_strategy: PricingStrategy | HourlyCost | None = None,
        payment_context: PaymentContext | None = None,
        *,
        hourly_cost: HourlyCost | None = None,
        payment_service: PaymentContext | None = None,
    ) -> None:
        if not floors:
            raise ValueError("A parking lot needs at least one floor")
        floor_ids = [floor.get_floor_id() for floor in floors]
        if len(floor_ids) != len(set(floor_ids)):
            raise ValueError("Floor IDs must be unique")
        if pricing_strategy is not None and hourly_cost is not None:
            raise ValueError("Provide either a pricing strategy or hourly cost")
        if pricing_strategy is None:
            pricing_strategy = hourly_cost
        if pricing_strategy is None:
            raise ValueError("A parking lot needs a pricing strategy")
        if payment_context is not None and payment_service is not None:
            raise ValueError("Provide either a payment context or payment service")

        self.floors = list(floors)
        self.active_tickets: dict[str, ParkingTicket] = {}
        self.active_plates: dict[str, str] = {}
        selected_context = payment_context if payment_context is not None else payment_service
        self.payment_context = selected_context if selected_context is not None else PaymentContext()
        self.payment_service = self.payment_context
        if isinstance(pricing_strategy, HourlyCost):
            pricing_strategy = TimeBasedPricingStrategy(pricing_strategy)
        self.pricing_strategy = pricing_strategy
        self.entry_panel = EntryPanel("ENTRY-1", self)
        self.exit_panel = ExitPanel(
            "EXIT-1", self, self.pricing_strategy, self.payment_context
        )

    def allocate_spot(
        self, vehicle: Vehicle
    ) -> tuple[ParkingFloor, ParkingSpot] | None:
        for floor in self.floors:
            spot = floor.allocate_spot(vehicle)
            if spot is not None:
                return floor, spot
        return None

    def release_spot(self, spot: ParkingSpot) -> None:
        for floor in self.floors:
            if floor.get_floor_id() == spot.floor_id:
                if floor.get_spot(spot.spot_id) is not spot:
                    raise RuntimeError("Spot does not belong to this floor")
                floor.release_spot(spot.spot_id)
                return
        raise RuntimeError("Spot does not belong to this lot")
