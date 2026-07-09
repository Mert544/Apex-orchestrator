"""Unit tests for :mod:`app.engine.node_impact` — node-level (not just
whole-FILE) impacted-test selection, strictly opt-in and fail-closed.

Each test pins one exact behavioral guarantee from the design: what gets
narrowed to a single node id, and what MUST fall back to the whole file
because the AST cannot prove it safe to narrow (never-fake-green applies to
node selection too — a selected set may only ever DROP a provably-unrelated
node, never lose one that could actually fail).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.node_impact import impacted_test_nodes


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _base_project(root: Path) -> None:
    """A minimal project: ``app/changed.py`` (the module we'll mutate) and
    ``app/other.py`` (an unrelated sibling), both importable as ``app.*``."""
    _write(root, "app/__init__.py", "")
    _write(root, "app/changed.py", "def thing():\n    return 1\n")
    _write(root, "app/other.py", "def other_thing():\n    return 2\n")
    _write(root, "tests/__init__.py", "")


# --- selection / dropping -------------------------------------------------

def test_single_node_selected_others_dropped(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n"
        "from app import other\n\n"
        "def test_a():\n"
        "    return changed.thing()\n\n"
        "def test_b():\n"
        "    return other.other_thing()\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::test_a"]
    assert fallback == []


def test_class_method_node_id_format(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "class TestFoo:\n"
        "    def test_bar(self):\n"
        "        return changed.thing()\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::TestFoo::test_bar"]
    assert fallback == []


# --- fail-closed whole-file fallback --------------------------------------

def test_star_import_forces_whole_file_fallback(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app.changed import *\n\n"
        "def test_a():\n"
        "    return thing()\n\n"
        "def test_b():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert not any(n.startswith("tests/test_x.py::") for n in node_ids)


def test_dynamic_import_literal_forces_fallback(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "import importlib\n\n"
        "def test_a():\n"
        "    mod = importlib.import_module(\"app.changed\")\n"
        "    return mod.thing()\n\n"
        "def test_b():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


def test_risky_module_level_code_forces_fallback(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def compute():\n"
        "    return 1\n\n"
        "X = compute()\n\n"
        "def test_a():\n"
        "    return changed.thing()\n\n"
        "def test_b():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


def test_undefined_conftest_fixture_forces_fallback(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def test_a(tmp_project):\n"
        "    return changed.thing()\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


def test_getattr_string_unanalyzable_node_forces_fallback(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def test_a():\n"
        "    return getattr(changed, \"thing\")()\n\n"
        "def test_b():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


# --- transitive closure ----------------------------------------------------

def test_transitive_helper_closure(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def _helper():\n"
        "    return changed.thing()\n\n"
        "def test_x():\n"
        "    return _helper()\n\n"
        "def test_y():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::test_x"]
    assert fallback == []


# --- sound bound-name matching (transitive imports) -----------------------

def test_transitive_import_bound_name_narrows_not_dropped(tmp_path):
    """Root cause: ``targets`` holds DOTTED module names, but a node's
    closure holds locally-BOUND identifiers — for a symbol reached only
    transitively (the test imports an intermediary that itself imports the
    changed module), the two could never intersect under a direct
    closure-vs-dotted-path comparison, so the node — and the whole file —
    would silently vanish from both ``node_ids`` and ``fallback_files``. The
    file must narrow to the specific node, not vanish or whole-file
    fallback."""
    _base_project(tmp_path)
    _write(tmp_path, "app/ascend.py", (
        "from app import changed\n\n"
        "def plan_ascend():\n"
        "    return changed.thing()\n"))
    _write(tmp_path, "tests/test_x.py", (
        "from app.ascend import plan_ascend\n\n"
        "def test_a():\n"
        "    return plan_ascend()\n\n"
        "def test_b():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::test_a"]
    assert fallback == []


def test_same_file_direct_and_transitive_imports_both_narrow(tmp_path):
    """Even in a file that ALSO imports the changed module directly, a node
    reaching the change ONLY through a same-file-bound intermediary symbol
    (not the changed module's own bound name) must still be selected — each
    node is judged on its own closure, independent of what other imports the
    file happens to have."""
    _base_project(tmp_path)
    _write(tmp_path, "app/ascend.py", (
        "from app import changed\n\n"
        "def plan_ascend():\n"
        "    return changed.thing()\n"))
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n"
        "from app.ascend import plan_ascend\n\n"
        "def test_direct():\n"
        "    return changed.thing()\n\n"
        "def test_indirect():\n"
        "    return plan_ascend()\n\n"
        "def test_unrelated():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == [
        "tests/test_x.py::test_direct", "tests/test_x.py::test_indirect",
    ]
    assert fallback == []


# --- safety floor: covering-but-unattributable never vanishes --------------

def test_imports_transitive_intermediary_but_unused_falls_back(tmp_path):
    """The file genuinely, transitively reaches the change (it imports an
    intermediary module that imports the changed module) but no test node's
    closure references that intermediary at all. Narrowing correctly selects
    zero nodes — the safety floor means that must still send the WHOLE FILE
    to ``fallback_files``, not silently drop it (distinct from the
    ``_narrow_file``-internal "no risky names at all" case: here the risky
    name set is non-empty, but no node's closure matches it)."""
    _base_project(tmp_path)
    _write(tmp_path, "app/intermediary.py", (
        "from app import changed\n\n"
        "def helper():\n"
        "    return changed.thing()\n"))
    _write(tmp_path, "tests/test_x.py", (
        "from app import intermediary\n\n"
        "def test_unrelated():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == []
    assert fallback == ["tests/test_x.py"]


def test_invariant_impacted_files_equal_node_files_union_fallback(tmp_path):
    """The exact live invariant behind the safety floor, on a fixture mixing
    all three outcomes at once: a file that narrows to a node, a file that
    narrows to a node only via a transitive symbol, and a file that must
    whole-file fallback. Every file the file-level gate
    (:func:`app.engine.test_impact.impacted_test_files`) calls impacted must
    land in EITHER ``node_ids`` (by its file component) OR
    ``fallback_files`` — never neither. This is exactly what the acute
    production bug violated (59 impacted files vanished from both lists on
    the real repo for a single changed file)."""
    from app.engine.test_impact import impacted_test_files

    _base_project(tmp_path)
    _write(tmp_path, "app/ascend.py", (
        "from app import changed\n\n"
        "def plan_ascend():\n"
        "    return changed.thing()\n"))
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def test_a():\n"
        "    return changed.thing()\n"))
    _write(tmp_path, "tests/test_y.py", (
        "from app.ascend import plan_ascend\n\n"
        "def test_b():\n"
        "    return plan_ascend()\n"))
    _write(tmp_path, "tests/test_z.py", (
        "from app import other\n\n"
        "def test_c():\n"
        "    return other.other_thing()\n"))
    changed = ["app/changed.py"]
    file_level = set(impacted_test_files(tmp_path, changed))
    node_ids, fallback = impacted_test_nodes(tmp_path, changed)
    covered = {n.split("::")[0] for n in node_ids} | set(fallback)
    assert covered == file_level
    assert node_ids == ["tests/test_x.py::test_a", "tests/test_y.py::test_b"]
    assert fallback == ["tests/test_z.py"]


# --- class-body execution ----------------------------------------------------

def test_class_level_computed_assignment_forces_fallback(tmp_path):
    """A ``Test*`` class body with a statement beyond defs/docstring/simple
    literal assigns (here, a call-computed class attribute) executes at
    IMPORT time — invisibly to any per-node closure — so narrowing that file
    is unsound; it must whole-file fallback rather than silently ignore the
    class-level computation."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def compute():\n"
        "    return 1\n\n"
        "class TestFoo:\n"
        "    X = compute()\n\n"
        "    def test_a(self):\n"
        "        return changed.thing()\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == []
    assert fallback == ["tests/test_x.py"]


def test_class_level_simple_literal_still_narrows(tmp_path):
    """A class-level simple literal assignment (no call, cannot compute a
    value from the change) is fine — this is not itself the bug, just a
    control case showing the class-body check does not over-trigger."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "class TestFoo:\n"
        "    TIMEOUT = 30\n\n"
        "    def test_a(self):\n"
        "        return changed.thing()\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::TestFoo::test_a"]
    assert fallback == []


# --- empty / degenerate ----------------------------------------------------

def test_file_level_only_match_falls_back_not_dropped(tmp_path):
    """A test file the FILE-level gate marks covering only via the coarse
    "imports a parent package of the changed module" over-approximation
    (``from app import changed`` also matches a change to ``app/lonely.py``,
    a sibling under the same ``app`` package) has no import whose source
    genuinely reaches ``lonely.py`` — node-level matching correctly finds no
    risky bound names. The safety floor means that must send the WHOLE FILE
    to ``fallback_files``, never silently drop it from both lists (the exact
    shape of the acute production bug: 59 files vanished from both lists on
    the real repo)."""
    _base_project(tmp_path)
    _write(tmp_path, "app/lonely.py", "def g():\n    return 9\n")
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def test_a():\n"
        "    return changed.thing()\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/lonely.py"])
    assert node_ids == []
    assert fallback == ["tests/test_x.py"]


# --- fixture-request patterns (indirect parametrize / usefixtures) --------

def test_indirect_parametrize_undefined_conftest_fixture_forces_fallback(tmp_path):
    """``indirect=True`` makes the parametrize name a genuine fixture request
    (pytest calls the same-named fixture with ``request.param``), not a
    literal value — an undefined (conftest-only) fixture requested this way
    must still force whole-file fallback, exactly like a plain parameter."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/conftest.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "@pytest.fixture\n"
        "def db(request):\n"
        "    return changed.thing()\n"))
    _write(tmp_path, "tests/test_x.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "def test_unrelated():\n"
        "    return 1\n\n"
        "@pytest.mark.parametrize('db', ['x'], indirect=True)\n"
        "def test_query(db):\n"
        "    assert db == 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


def test_indirect_parametrize_defined_fixture_still_narrows(tmp_path):
    """An ``indirect=True`` fixture defined IN-FILE (not conftest) is fine to
    narrow normally — this is not itself the bug, just a control case."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "@pytest.fixture\n"
        "def db(request):\n"
        "    return changed.thing()\n\n"
        "def test_unrelated():\n"
        "    return 1\n\n"
        "@pytest.mark.parametrize('db', ['x'], indirect=True)\n"
        "def test_query(db):\n"
        "    assert db == 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::test_query"]
    assert fallback == []


def test_usefixtures_undefined_conftest_fixture_forces_fallback(tmp_path):
    """A fixture requested only via ``@pytest.mark.usefixtures(...)`` (no
    matching parameter) that is defined in conftest (not in-file) must force
    whole-file fallback like any other undefined conftest fixture."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/conftest.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "@pytest.fixture\n"
        "def setup_db():\n"
        "    changed.thing()\n"))
    _write(tmp_path, "tests/test_x.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "def test_unrelated():\n"
        "    return 1\n\n"
        "@pytest.mark.usefixtures('setup_db')\n"
        "def test_query():\n"
        "    assert True\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


def test_usefixtures_in_file_fixture_pulls_closure(tmp_path):
    """A fixture requested via ``@pytest.mark.usefixtures(...)`` and defined
    IN-FILE contributes its references to the node's closure — the node is
    selected because the fixture (not the body) reaches the changed module."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "@pytest.fixture\n"
        "def setup_db():\n"
        "    changed.thing()\n\n"
        "@pytest.mark.usefixtures('setup_db')\n"
        "def test_query():\n"
        "    assert True\n\n"
        "def test_unrelated():\n"
        "    return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::test_query"]
    assert fallback == []


def test_class_level_usefixtures_undefined_fixture_forces_fallback(tmp_path):
    """A ``@pytest.mark.usefixtures(...)`` decorator on the enclosing TEST
    CLASS (applying to every method) is consulted too, not just per-method
    decorators — an undefined conftest fixture requested this way must also
    force fallback."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/conftest.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "@pytest.fixture\n"
        "def setup_db():\n"
        "    changed.thing()\n"))
    _write(tmp_path, "tests/test_x.py", (
        "import pytest\n"
        "from app import changed\n\n"
        "@pytest.mark.usefixtures('setup_db')\n"
        "class TestFoo:\n"
        "    def test_bar(self):\n"
        "        assert True\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


# --- class inheritance -----------------------------------------------------

def test_inherited_test_method_from_same_file_mixin_included(tmp_path):
    """A ``test_*`` method a ``Test*`` class inherits from a same-file mixin
    is a real, pytest-collected node — it must be discovered and, if its
    (inherited) body reaches the changed module, selected; it must never be
    silently dropped from both ``node_ids`` and ``fallback_files``."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "class Mixin:\n"
        "    def test_shared(self):\n"
        "        return changed.thing()\n\n"
        "class TestFoo(Mixin):\n"
        "    def test_own(self):\n"
        "        return 1\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert node_ids == ["tests/test_x.py::TestFoo::test_shared"]
    assert fallback == []


def test_unresolvable_base_class_forces_fallback(tmp_path):
    """A base class that cannot be resolved in-file (imported from elsewhere)
    might itself contribute more ``test_*`` methods the AST cannot see —
    unprovable, so the whole file must fall back rather than silently
    dropping whatever those inherited methods might be."""
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "import unittest\n"
        "from app import changed\n\n"
        "class TestFoo(unittest.TestCase):\n"
        "    def test_own(self):\n"
        "        return changed.thing()\n"))
    node_ids, fallback = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert fallback == ["tests/test_x.py"]
    assert node_ids == []


# --- determinism -------------------------------------------------------------

def test_deterministic_sorted_output(tmp_path):
    _base_project(tmp_path)
    _write(tmp_path, "tests/test_x.py", (
        "from app import changed\n\n"
        "def test_c():\n"
        "    return changed.thing()\n\n"
        "def test_a():\n"
        "    return changed.thing()\n\n"
        "def test_b():\n"
        "    return changed.thing()\n"))
    first = impacted_test_nodes(tmp_path, ["app/changed.py"])
    second = impacted_test_nodes(tmp_path, ["app/changed.py"])
    assert first == second
    assert first[0] == sorted(first[0])
