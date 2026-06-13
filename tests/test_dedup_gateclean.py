"""Gate-cleanliness of the dedup-extract transform.

Lifting a duplicated block into a shared helper can strand the imports that the
block used: those names are no longer referenced in the original module, leaving
``F401 imported but unused`` and turning the suite red (the exact dogfood
self-dedup failure that left ``_py_files`` and ``json`` unused). These tests pin
that dedup's emitted ``new_contents`` carry zero unused imports — while an import
that is STILL used elsewhere in the file is kept untouched.
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


# ── 1. cross-file: the importing module's strand is removed (the dogfood bug) ──

# Two modules share an identical 5-statement block that calls ``json.dumps``.
# The helper lands in the FIRST module (which keeps ``json`` — the helper calls
# it). In the OTHER module the copy collapses to a bare ``_shared_n(...)`` call,
# so that module no longer references ``json`` — a stranded F401 (exactly the
# self-dedup failure that left ``json`` unused) unless dedup gate-cleans output.
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


def test_stranded_import_is_removed(tmp_path):
    root = tmp_path
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/a.py", _STRAND_A)
    _write(root, "pkg/b.py", _STRAND_B)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks, "the detector should find the shared block"

    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"

    first = plan.defined_in
    other = next(r for r in plan.new_contents if r != first)
    other_src = plan.new_contents[other]

    # The emitted module still parses and the now-dead `json` import is gone.
    ast.parse(other_src)
    assert "json" not in _imported_names(other_src)
    assert "import json" not in other_src
    # The helper call replaced the copy, and the helper import survives (used).
    assert f"{plan.new}(" in other_src
    assert f"import {plan.new}" in other_src

    # Running the detector on the emitted source confirms it is gate-clean:
    # strip_unused_imports finds nothing more to remove.
    assert strip_unused_imports(other_src) is None


# ── 2. an import STILL used elsewhere in the file is KEPT ──

# Cross-file again, but the OTHER module also has ``gamma`` (a non-duplicated
# function) that ALSO uses ``json``. After the duplicated copy collapses to a
# call, ``json`` is *still* referenced by ``gamma`` — so gate-cleaning must KEEP
# the import (it removes only genuinely-dead bindings, never live ones).
_KEEP_A = '''\
import json


def alpha(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label
'''

_KEEP_B = '''\
import json


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
    _write(root, "pkg/a.py", _KEEP_A)
    _write(root, "pkg/b.py", _KEEP_B)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks

    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"

    first = plan.defined_in
    other = next(r for r in plan.new_contents if r != first)
    other_src = plan.new_contents[other]

    ast.parse(other_src)
    # gamma still references json in the OTHER module → the import is kept.
    assert "import json" in other_src
    assert "json" in _imported_names(other_src)
    assert "def gamma(" in other_src
    # And the module is still gate-clean (the live import is not flagged).
    assert strip_unused_imports(other_src) is None


# ── 3. cross-file: the importing module keeps the helper import (it's used) ──

_CROSS_A = '''\
import json


def alpha(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label
'''

_CROSS_B = '''\
import json


def beta(data):
    payload = {"a": 1}
    text = json.dumps(payload)
    size = len(text)
    marker = size + 1
    label = marker * 2
    return label + 7
'''


def test_cross_file_gate_clean_both_modules(tmp_path):
    root = tmp_path
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/a.py", _CROSS_A)
    _write(root, "pkg/b.py", _CROSS_B)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks

    plan = plan_dedup_extract(root, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"

    first = plan.defined_in
    other = next(r for r in plan.new_contents if r != first)
    first_src = plan.new_contents[first]
    other_src = plan.new_contents[other]

    # Both modules parse and neither carries an unused import (gate-clean).
    for src in (first_src, other_src):
        ast.parse(src)
        assert strip_unused_imports(src) is None

    # The defining module keeps json (the helper still calls json.dumps);
    # the other module no longer references json (its copy became a call), so
    # its json import is stripped — but the helper import is kept (it's used).
    assert "json.dumps" in first_src
    assert "json" not in _imported_names(other_src)
    assert f"import {plan.new}" in other_src


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
