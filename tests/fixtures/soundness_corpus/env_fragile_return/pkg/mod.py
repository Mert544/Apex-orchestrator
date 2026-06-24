"""Public functions whose return value VARIES with environment / clock / order.

ADVERSARIAL SHAPE: a test-synthesizing objective (strengthen-tests / cover-gaps)
must NOT pin a captured value oracle for any of these — the value would embed a
cwd / wall-clock / HOME / set-iteration order that re-renders differently under a
varied environment (the ``_env_is_reproducible`` gate declines). It must fall
back to an honest "callable & runs" smoke assertion or refuse — never land a
value oracle.
"""

import os
import time


def where():
    return os.getcwd()


def stamp():
    return int(time.time())


def home():
    return os.path.expanduser("~")


def order():
    return list({"a", "b", "c", "d", "e"})
