"""The star-EXPORT target: a public module imported via ``from pkg.a import *``.

ADVERSARIAL SHAPE: module ``b`` does ``from pkg.a import *``. Landing an explicit
``__all__`` here would SHRINK the star set (``__all__`` would exclude the imported
``os`` that a bare ``import *`` currently re-exports), changing what ``b`` sees.
wire-module-exports must therefore REFUSE (``project_has_star_consumer`` -> True).
"""

import os


def public_a():
    return os.getpid


def helper_a():
    return 2
