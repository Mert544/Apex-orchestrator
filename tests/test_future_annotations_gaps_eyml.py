"""add-from-future-annotations — regression / characterization lock.

:mod:`app.execution.future_annotations` is ALREADY at 100% line coverage from
``test_from_future_annotations_objective_eyml``. This file adds NO new coverage; it
pins the module's documented public contract (fresh-insert placement, widen-in-place
with sorted names, and the three honest no-op refusals) so a future refactor of the
transform cannot silently drift the landed bytes. Deterministic, offline, pure AST.
"""

from __future__ import annotations

import ast

from app.execution.future_annotations import (
    add_future_annotations,
    has_future_annotations,
    module_uses_annotations,
)

_TYPED = '"""Doc."""\nimport os\n\n\ndef f(x: int) -> int:\n    return x\n'


def test_fresh_insert_lands_after_docstring():
    out = add_future_annotations(_TYPED)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == '"""Doc."""'  # docstring stays first
    assert "from __future__ import annotations" in lines
    assert has_future_annotations(out)
    ast.parse(out)


def test_widen_existing_future_import_keeps_names_sorted():
    # An existing ``from __future__ import division`` is widened in place (never a
    # second __future__ line) with the feature names kept in sorted order.
    src = "from __future__ import division\n\nx: int = 0\n"
    out = add_future_annotations(src)
    assert out is not None
    assert out.count("from __future__ import") == 1
    assert "from __future__ import annotations, division" in out.splitlines()
    ast.parse(out)


def test_noop_when_no_annotations_used():
    # Nothing to defer -> honest no-op (adding the import would be pure noise).
    assert not module_uses_annotations("def f(x, y):\n    return x + y\n")
    assert add_future_annotations("def f(x, y):\n    return x + y\n") is None


def test_noop_when_already_deferred_and_on_syntax_error():
    already = "from __future__ import annotations\n\nx: int = 0\n"
    assert has_future_annotations(already)
    assert add_future_annotations(already) is None  # idempotent
    assert add_future_annotations("def (:\n") is None  # never rewrite broken source
