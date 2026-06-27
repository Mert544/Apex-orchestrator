"""A package whose PUBLIC API is a re-export with NO module-level ``__all__``.

ADVERSARIAL SHAPE: this ``__init__.py`` does ``from .mod import public_fn`` purely
to surface ``public_fn`` as ``pkg.public_fn`` (the standard package-init re-export
convention). The name is never USED locally in this file and there is NO ``__all__``
to mark it as kept, so a path-blind remove-unused-imports reads it as a dead import
and would DELETE the line — silently dropping the package's public export. A
suite that imports ``pkg.mod.public_fn`` directly stays green, so the move would
ship ``weak (uncovered)`` and land on a broad ``--apply`` sweep. remove-unused-imports
must REFUSE every ``__init__.py`` (the re-export survives).
"""

from .mod import public_fn
