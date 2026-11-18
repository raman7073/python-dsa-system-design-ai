from shared.spot_allocation_strategy import SpotAllocationStrategy


class BestFitStrategy(SpotAllocationStrategy):
    """Smallest spot that fits (a bike only takes a car spot if bike spots are full), then nearest."""

    def find_spot(self, v, spots):
        return min(
            (s for s in spots if s.can_fit(v)),
            key=lambda s: (s.size, s.distance),
            default=None  # Returns None if no spot fits (replaces Optional.empty())
        )