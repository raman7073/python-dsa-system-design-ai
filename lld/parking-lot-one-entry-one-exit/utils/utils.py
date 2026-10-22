"""Interchangeable ways to price a parking stay (amounts are in cents)."""

from datetime import datetime, timedelta, timezone

from hourly_cost import HourlyCost
from parking_ticket import ParkingTicket


def stay_duration(ticket: ParkingTicket, exit_time: datetime) -> timedelta:
    """Validate the timestamps once for every pricing rule."""
    entry_time = ticket.entry_time
    for moment in (entry_time, exit_time):
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Parking times must have a timezone")
    duration = exit_time.astimezone(timezone.utc) - entry_time.astimezone(timezone.utc)
    if duration < timedelta(0):
        raise ValueError("Exit time cannot be before entry time")
    return duration


def billable_hours(ticket: ParkingTicket, exit_time: datetime) -> int:
    """Charge each started hour, with no charge for a zero-length stay."""
    duration = stay_duration(ticket, exit_time)
    microseconds = (
        duration.days * 86_400_000_000
        + duration.seconds * 1_000_000
        + duration.microseconds
    )
    microseconds_per_hour = 3_600_000_000
    return (microseconds + microseconds_per_hour - 1) // microseconds_per_hour




