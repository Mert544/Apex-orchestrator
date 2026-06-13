"""Self-registering develop objectives.

Every module here registers one develop objective with the develop registry at
import (see ``app.engine.develop_registry``). Drop a new ``<name>.py`` here that
calls ``register(ObjectiveSpec(...))`` and the objective becomes live across
``apex develop``/``plan``/``ascend`` — no hub edit, so modules never conflict.
"""
