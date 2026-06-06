from smctrader.sessions import killzone, in_killzone


def test_killzone_windows():
    assert killzone(3) == "asian"
    assert killzone(8) == "london_open"
    assert killzone(13) == "new_york_open"
    assert killzone(16) == "london_close"
    assert killzone(22) == "off_session"


def test_in_killzone_and_wraparound():
    assert in_killzone(8) is True
    assert in_killzone(22) is False
    assert killzone(8 + 24) == "london_open"   # hour normalised mod 24
