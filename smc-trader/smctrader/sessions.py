"""ICT session killzones, mapped from the bar's UTC hour."""


# (start_hour_inclusive, end_hour_exclusive, name) in UTC. ICT killzones are the
# high-probability windows around the London and New York opens.
_KILLZONES = (
    (0, 5, "asian"),
    (7, 10, "london_open"),
    (12, 15, "new_york_open"),
    (15, 17, "london_close"),
)


def killzone(utc_hour: int) -> str:
    """The killzone for a given UTC hour, or 'off_session'."""
    hour = utc_hour % 24
    for start, end, name in _KILLZONES:
        if start <= hour < end:
            return name
    return "off_session"


def in_killzone(utc_hour: int) -> bool:
    """True if the hour falls in any high-probability killzone window."""
    return killzone(utc_hour) != "off_session"
