"""Gate-cleanliness of the dedup-extract transform.

Lifting a duplicated block into a shared helper can strand the imports that the
block used: those names are no longer referenced in the original module, leaving
``F401 imported but unused`` and turning the suite red (the exact dogfood
self-dedup failure that left ``_py_files`` and ``json`` unused). These tests pin
that dedup's emitted ``new_contents`` carry zero unused imports — while an import
that is STILL used elsewhere in the file is kept untouched.

W97 soundness-rail interaction: a CROSS-FILE run that reads an import-bound
name (``json``) is exactly the "free module-global rebinds to the defining
module's value" shape the family rails now REFUSE — so the cross-file
stranded-import scenario can no longer land (it is pinned here as a blocker).
Gate-cleaning stays pinned on its still-reachable single-module forms, where
the helper lives beside the import it uses.
"""

from __future__ import annotations

import ast

from app.engine.dedup import find_duplicates
from app.execution.dedup_extract import plan_dedup_extract
from app.execution.unused_imports import strip_unused_imports


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _imported_names(source: str) -> set[str]:
    """Every top-level bound import name in ``source`` (for F401 assertions)."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


# ── 1. cross-file strand shape: REFUSED by the family soundness rails ──

# Two modules share an identical 5-statement block that calls ``json.dumps``.
# Before W97 the helper landed in the FIRST module and the OTHER module's
# ``json`` import was gate-cleaned. But the run READS ``json`` — a free
# module-global — so collapsing the copies into one module would rebind it to
# the defining module's binding (the adversarially-verified cross-module
# rebind hazard: the same shape with differing module globals silently changes
# behaviour). The family rail now refuses the whole shape.
_STRAND_A = '''\
import json


def alpha(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label
'''

_STRAND_B = '''\
import json


def beta(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label + 100
'''


def test_cross_file_import_reading_block_is_refused(tmp_path):
    root = tmp_path
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/a.py", _STRAND_A)
    _write(root, "pkg/b.py", _STRAND_B)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks, "the detector should find the shared block"

    plan = plan_dedup_extract(root, blocks[0])
    assert not plan.ok, "a cross-module run reading a free module-global must block"
    assert any("free module-global would rebind to the defining module's value"
               in b for b in plan.blockers)
    assert not plan.new_contents


# ── 2. an import STILL used elsewhere in the file is KEPT ──

# Single module (the sound class): alpha/beta share the duplicated block and
# ``gamma`` ALSO uses ``json``. After the copies collapse, ``json`` is still
# referenced (helper + gamma) — gate-cleaning must KEEP the import (it removes
# only genuinely-dead bindings, never live ones).
_KEEP = '''\
import json


def alpha(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label


def beta(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label + 100


def gamma(obj):
    return json.dumps(obj)
'''


def test_import_still_used_elsewhere_is_kept(tmp_path):
    root = tmp_path
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/mod.py", _KEEP)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks

    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]

    ast.parse(new_src)
    # The helper AND gamma still reference json → the import is kept.
    assert "import json" in new_src
    assert "json" in _imported_names(new_src)
    assert "def gamma(" in new_src
    # And the module is still gate-clean (the live import is not flagged).
    assert strip_unused_imports(new_src) is None


# ── 3. single-module lift beside its import stays gate-clean end-to-end ──

_SAME_MODULE_IMPORT = '''\
import json


def alpha(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label


def beta(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label + 7
'''


def test_same_module_helper_keeps_import_gate_clean(tmp_path):
    root = tmp_path
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/mod.py", _SAME_MODULE_IMPORT)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks

    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]

    # The module parses and carries no unused import (gate-clean): the helper
    # lives beside the import it uses, so ``json`` stays live.
    ast.parse(new_src)
    assert strip_unused_imports(new_src) is None
    assert "json.dumps" in new_src
    assert "import json" in new_src
    assert f"def {plan.new}(" in new_src


# ── 4. no stranded import → output is byte-for-byte the pre-clean extraction ──

# When the block uses no imports, gate-cleaning is a no-op: dedup's output is
# exactly what it was before this fix (behaviour otherwise identical).
_NO_IMPORTS = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e


def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e + 5
'''


def test_no_imports_extraction_unchanged(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _NO_IMPORTS)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks

    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    ast.parse(new_src)
    # Nothing to clean — and the helper extraction still happened.
    assert strip_unused_imports(new_src) is None
    assert f"def {plan.new}(" in new_src
