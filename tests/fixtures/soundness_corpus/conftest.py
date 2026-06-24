"""Keep the soundness corpus OUT of pytest collection.

These fixtures are tiny standalone projects an objective is RUN against by
``app/engine/soundness_audit.py`` — not test modules of the Apex suite. One of
them (``env_fragile_return/tests/test_mod.py``) is named ``test_*.py`` so the
``strengthen-tests`` objective discovers it as the module's existing test file;
without this guard pytest would try to import it from the wrong root and ERROR at
collection. ``collect_ignore_glob`` makes pytest skip everything under this corpus
directory while leaving the files on disk for the audit to read.
"""

from __future__ import annotations

collect_ignore_glob = ["*"]
