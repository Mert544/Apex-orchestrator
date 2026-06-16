"""The code-quality scans extracted into ``app/tools/profile_scanners.py`` are
still reachable, transparent, and behavior-preserving through the public
``ProjectProfiler(...).profile()`` path.

This guards the structural move: the scans now live on ``_CodeQualityScansMixin``
which ``ProjectProfiler`` inherits, so every call site stays ``self._scan_x(...)``
and the profile fields they populate (``coordinator_modules``,
``extractable_blocks``, ``inlinable_helpers``, ``dead_params``,
``generalizable_duplications``, ``incomplete_protocols``) are filled exactly as
before — including the empty-path (all-clean repo) case.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from app.tools.profile_scanners import _CodeQualityScansMixin
from app.tools.project_profile import ProjectProfiler


def test_profiler_inherits_extracted_mixin():
    """The extracted scans live on the mixin and ProjectProfiler inherits them."""
    assert issubclass(ProjectProfiler, _CodeQualityScansMixin)
    for name in (
        "_scan_extractable_blocks",
        "_scan_inlinable_helpers",
        "_scan_dead_params",
        "_scan_generalizable_duplications",
        "_scan_coordinator_modules",
        "_scan_incomplete_protocols",
        "_is_execution_scaffold_module",
    ):
        # Resolved through inheritance — defined on the mixin, callable on the
        # ProjectProfiler instance exactly as before.
        assert hasattr(ProjectProfiler, name)
        assert name in vars(_CodeQualityScansMixin)
        assert name not in vars(ProjectProfiler)
    # The constants the cluster owns moved with it.
    for const in (
        "_GENERALIZE_MAX_MODULES",
        "_EXECUTION_SCAFFOLD_DIR",
        "_EXECUTION_SCAFFOLD_IMPORTS",
        "_COORDINATOR_FAN_OUT_FLOOR",
    ):
        assert const in vars(_CodeQualityScansMixin)
        # Still reachable via the ProjectProfiler class (inheritance).
        assert hasattr(ProjectProfiler, const)


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_extracted_scans_populate_fields_via_public_profile(tmp_path):
    """The move is transparent: extracted scans still fill their fields through
    the public ``profile()`` path (non-light, as the idea engine profiles)."""
    # A coordinator module: imports >= the fan-out floor of internal modules.
    n = ProjectProfiler._COORDINATOR_FAN_OUT_FLOOR + 2
    imports = "".join(f"from app.dep{i} import thing{i}\n" for i in range(n))
    for i in range(n):
        _write(tmp_path, f"app/dep{i}.py", f"def thing{i}():\n    return {i}\n")
    _write(tmp_path, "app/god.py", imports + "\n\ndef wire():\n    return 1\n")

    # An incomplete protocol: __eq__ without __hash__.
    _write(
        tmp_path,
        "app/contract.py",
        """
        class Money:
            def __init__(self, amount):
                self.amount = amount

            def __eq__(self, other):
                return self.amount == other.amount
        """,
    )

    profiler = ProjectProfiler(tmp_path)
    profile = profiler.profile()

    # These fields exist and are produced by the extracted scans (they are lists,
    # never None, after a full profile run).
    assert isinstance(profile.coordinator_modules, list)
    assert isinstance(profile.extractable_blocks, list)
    assert isinstance(profile.inlinable_helpers, list)
    assert isinstance(profile.dead_params, list)
    assert isinstance(profile.generalizable_duplications, list)
    assert isinstance(profile.incomplete_protocols, list)

    # The coordinator scan flagged the god-module via the inherited mixin method.
    coord_modules = {e["module"] for e in profile.coordinator_modules}
    assert "app/god.py" in coord_modules

    # The incomplete-protocol scan flagged the __eq__/__hash__ gap.
    protos = {p["class"] for p in profile.incomplete_protocols}
    assert "Money" in protos


def test_extracted_scans_empty_on_clean_repo(tmp_path):
    """Edge/empty path: a repo with nothing to flag yields [] for every extracted
    field — the move preserves the byte-identical all-clean behavior."""
    _write(tmp_path, "app/simple.py", "def f(x):\n    return x + 1\n")

    profile = ProjectProfiler(tmp_path).profile()

    assert profile.coordinator_modules == []
    assert profile.generalizable_duplications == []
    assert profile.incomplete_protocols == []
    assert profile.extractable_blocks == []
    # dead_params/inlinable_helpers are conservative; this trivial module yields
    # nothing for them either.
    assert profile.dead_params == []
    assert profile.inlinable_helpers == []


def test_dead_params_isolated_helper_still_works(tmp_path):
    """The standalone ``dead_params()`` API (which calls the now-inherited
    ``_scan_dead_params``) still returns the never-read parameters."""
    _write(
        tmp_path,
        "app/widget.py",
        """
        def configure_widget(width, height, unused_knob):
            return width * height
        """,
    )
    params = ProjectProfiler(tmp_path).dead_params()
    flagged = {(d["function"], d["param"]) for d in params}
    assert ("configure_widget", "unused_knob") in flagged


# --- characterization: routing the AST scans through iter_source_files is a
# --- pure perf change — the profile fields are pinned byte-for-byte. ---


def _representative_project(root: Path) -> None:
    """A small but varied project that exercises every scan converted to
    ``iter_source_files``: a long function with a clean extract seam, a unique
    function with a never-read param, a single-use return helper, a high-fan-out
    coordinator, a deeply nested function and a god-class — plus fixture/test
    paths that every scan must exclude."""
    # extractable seam: a long accumulation run inside one function.
    acc = "\n".join(f"    acc = acc + {i}" for i in range(45))
    _write(root, "app/big.py", f"def compute(start):\n    acc = start\n{acc}\n    return acc\n")
    # dead param: unique top-level function with an unread knob.
    _write(root, "app/widget.py", """
        def configure_widget(width, height, unused_knob):
            return width * height
    """)
    # inlinable: single-use return-only helper.
    _write(root, "app/calc.py", """
        def fee(x):
            return x * 2


        def total(price):
            return fee(price) + 1
    """)
    # coordinator: imports >= the fan-out floor of internal modules.
    n = ProjectProfiler._COORDINATOR_FAN_OUT_FLOOR + 2
    imports = "".join(f"from app.dep{i} import thing{i}\n" for i in range(n))
    for i in range(n):
        _write(root, f"app/dep{i}.py", f"def thing{i}():\n    return {i}\n")
    _write(root, "app/god.py", imports + "\n\ndef wire():\n    return 1\n")
    # deeply nested function (5 compound statements deep).
    _write(root, "app/nested.py", """
        def staircase(items):
            for a in items:
                if a:
                    while a:
                        with open("x") as f:
                            try:
                                return f
                            except OSError:
                                return None
    """)
    # god-class: more methods than the floor.
    methods = "\n".join(f"    def m{i}(self):\n        self.x{i} = {i}\n"
                        for i in range(ProjectProfiler._GOD_CLASS_METHOD_FLOOR + 1))
    _write(root, "app/huge.py", f"class Huge:\n{methods}")
    # fixture/test/example paths every scan must exclude.
    _write(root, "tests/test_thing.py", """
        def configure_widget_fixture(a, b, dead_one):
            return a
    """)
    _write(root, "examples/demo.py", """
        def demo(p, q, dead_two):
            return p
    """)


# The exact profile fields produced by the scans this change touched.
_PINNED_FIELDS = (
    "extractable_blocks", "inlinable_helpers", "dead_params",
    "coordinator_modules", "god_classes", "deeply_nested_functions",
)


def test_iter_source_files_routing_pins_scan_fields(tmp_path):
    """The converted scans (extractable/inlinable/dead-param/coordinator/
    god-class/deep-nesting) produce the pinned values on a representative
    project — this nails down the byte-identical output the perf refactor must
    preserve, including the fixture/test/example exclusion."""
    _representative_project(tmp_path)
    profile = ProjectProfiler(tmp_path).profile()
    fields = {name: getattr(profile, name) for name in _PINNED_FIELDS}

    # extractable: the one long function, no fixture leakage.
    assert [b["module"] for b in fields["extractable_blocks"]] == ["app/big.py"]
    assert fields["extractable_blocks"][0]["function"] == "compute"
    # inlinable: the single-use helper only.
    assert fields["inlinable_helpers"] == [
        {"module": "app/calc.py", "function": "fee", "line": 2, "call_sites": 1}
    ]
    # dead params: only the real-code knob — fixture/example params excluded.
    assert fields["dead_params"] == [
        {"module": "app/widget.py", "function": "configure_widget",
         "param": "unused_knob", "line": 2}
    ]
    # coordinator: the one god-module.
    assert [c["module"] for c in fields["coordinator_modules"]] == ["app/god.py"]
    # god-class + deep nesting surface their single subjects.
    assert [g["classname"] for g in fields["god_classes"]] == ["Huge"]
    assert [d["function"] for d in fields["deeply_nested_functions"]] == ["staircase"]

    # No converted scan ever leaks a fixture/test/example path.
    for name in _PINNED_FIELDS:
        for entry in fields[name]:
            mod = entry["module"]
            assert not mod.startswith(("tests/", "examples/")), (name, mod)


def test_dead_params_excludes_claude_worktree_copies(tmp_path):
    """Routing ``_scan_dead_params`` through ``iter_source_files`` makes it
    worktree-safe like its sibling scans: a FULL repo copy under
    ``.claude/worktrees`` (which sorts first and would otherwise crowd the
    ``max_files`` budget) is pruned, so only the real source surfaces."""
    _write(tmp_path, "app/widget.py", """
        def configure_widget(width, height, unused_knob):
            return width * height
    """)
    # A byte-for-byte worktree copy under .claude — must never be considered.
    _write(tmp_path, ".claude/worktrees/agent-x/app/widget.py", """
        def configure_widget(width, height, unused_knob):
            return width * height
    """)
    params = ProjectProfiler(tmp_path).dead_params()
    modules = {d["module"] for d in params}
    assert modules == {"app/widget.py"}
    assert all(".claude" not in m for m in modules), params
