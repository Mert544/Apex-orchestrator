"""The star-EXPORT target observed through a RELATIVE star import.

ADVERSARIAL SHAPE: a sibling does ``from . import *`` (level>=1). A relative star
import must be treated as a potential observer (``_source_observes_star``,
level>=1 branch), so shrinking this module's star set with an explicit ``__all__``
must be REFUSED just like the absolute-import case.
"""

import json


def public_rel():
    return json.dumps


def helper_rel():
    return 3
