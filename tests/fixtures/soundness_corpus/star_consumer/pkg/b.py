"""The star CONSUMER: it observes ``pkg.a``'s star set via ``from pkg.a import *``.

The wildcard reference below keeps ``import *`` "used" without any top-level side
effect (no bare ``print`` that would leak to a subprocess probe's stdout).
"""

from pkg.a import *  # noqa: F401,F403


def use_star():
    return public_a  # noqa: F405  -- observed through the star import
