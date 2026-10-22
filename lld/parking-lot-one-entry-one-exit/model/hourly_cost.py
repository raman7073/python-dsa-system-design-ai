class HourlyCost:
    """Store the price, in cents, for one hour in each spot type."""

    def __init__(self, rates: dict[str, int]) -> None:
        self.rates: dict[str, int] = dict(rates)
        for spot_type, cents in self.rates.items():
            if not isinstance(cents, int) or cents < 0:
                raise ValueError("Rates must be non-negative integer cents")

    def get_rate(self, spot_type: str) -> int:
        if spot_type not in self.rates:
            raise ValueError("No hourly rate for spot type: " + spot_type)
        return self.rates[spot_type]

    def calculate(self, spot_type: str, hours: int) -> int:
        if not isinstance(hours, int) or hours < 0:
            raise ValueError("Hours must be a non-negative integer")
        return self.get_rate(spot_type) * hours
