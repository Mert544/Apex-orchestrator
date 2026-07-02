"""The inherited ``PYTHONPATH`` a TARGET-project child process may keep.

Every engine that proves a change by re-running the TARGET project's own tests
or probes in a fresh subprocess prepends the target root to ``PYTHONPATH`` so
the target's packages resolve on a bare environment. But the INHERITED tail
must never carry Apex's OWN repo root: the proof gate (``scripts/verify.py``)
pins that root into every chunk's environment so APEX-internal grandchildren
can import ``app`` — and if that pin leaks into a TARGET child, Apex's ``app``
(a REGULAR package, ``__init__.py`` present) silently defeats a target package
of the same name that is a NAMESPACE package (no ``__init__.py``): regular
packages win over namespace portions REGARDLESS of ``sys.path`` order, so even
"target root first" cannot protect the target. Observed end-to-end: a stub
project with ``app/calc.py`` (no ``__init__``) under the pinned gate collected
``from app.calc import total`` against APEX's ``app`` → ``ModuleNotFoundError:
No module named 'app.calc'`` → every impacted-test verification failed → every
landing was rolled back (honest, but a total capability loss inside the gate;
17 tests across 4 chunk families went red). Same self-sufficiency family as
the test-shield probe preamble and the verify.py chunk pin — this is the
boundary where the tool's own import convenience must STOP propagating.
"""

from __future__ import annotations

import os
from pathlib import Path

# Apex's own repo root (this file lives at <root>/app/execution/target_env.py).
_APEX_ROOT = Path(__file__).resolve().parents[2]


def inherited_pythonpath() -> str:
    """The ambient ``PYTHONPATH`` with Apex's own repo root scrubbed out.

    Preserves every other inherited entry in its original order (a
    caller-supplied path for the TARGET stays honoured); only entries that
    resolve to the Apex checkout itself are dropped, and empty entries are
    discarded. An unresolvable entry is kept — it is not ours to judge.
    """
    kept: list[str] = []
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if Path(entry).resolve() == _APEX_ROOT:
                continue
        except OSError:
            pass
        kept.append(entry)
    return os.pathsep.join(kept)
