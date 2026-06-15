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
