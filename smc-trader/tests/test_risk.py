from smctrader.risk import position_size, r_multiple


def test_position_size_risks_exact_fraction():
    # risk 1% of 1000 = 10; stop distance 10 -> 1.0 unit (losing the stop loses $10)
    assert position_size(1000.0, 1.0, 100.0, 90.0) == 1.0
    assert position_size(1000.0, 2.0, 100.0, 95.0) == 4.0


def test_position_size_guards():
    assert position_size(1000.0, 1.0, 100.0, 100.0) == 0.0   # zero stop distance
    assert position_size(0.0, 1.0, 100.0, 90.0) == 0.0


def test_r_multiple():
    assert r_multiple(100.0, 90.0, 130.0) == 3.0             # risk 10, reward 30
    assert r_multiple(100.0, 100.0, 130.0) == 0.0            # no risk -> 0
