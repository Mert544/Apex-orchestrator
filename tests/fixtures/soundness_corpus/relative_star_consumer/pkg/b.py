"""A RELATIVE star consumer: ``from . import *`` (level 1).

The relative wildcard must count as an observer of every sibling's star set, so
wire-module-exports refuses to shrink a sibling module's star set.
"""

from . import *  # noqa: F401,F403


def use_rel():
    return helper_rel  # noqa: F405  -- observed through the relative star import
