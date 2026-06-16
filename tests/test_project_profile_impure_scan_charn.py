"""Characterization test for ``_scan_impure_untested_functions``.

Proves the decomposition into ``_prepare_impure_module`` /
``_impure_untested_hit`` is behaviour-preserving: the full ``ProjectProfile``
emitted by the live (refactored) ``ProjectProfiler`` is byte-identical to the
one emitted by a frozen snapshot of the pre-refactor module, in BOTH light and
full mode, over representative temp trees.

The snapshot path is supplied via the ``APEX_PP_ORIG_SNAPSHOT`` env var (a copy
of ``git show HEAD:app/tools/project_profile.py`` kept under /tmp). When it is
absent the byte-identical comparison is skipped, but the edge/empty-path unit
checks below still run unconditionally so the new helpers stay covered.
"""

import dataclasses
import importlib.util
import json
import os
import textwrap

import pytest

from app.tools.project_profile import ProjectProfiler


def _serialize(profile) -> str:
    data = (
        dataclasses.asdict(profile)
        if dataclasses.is_dataclass(profile)
        else dict(vars(profile))
    )
    return json.dumps(data, default=str, sort_keys=True, indent=2)


def _build_tree(base):
    files = {
        "app/__init__.py": "",
        "app/core.py": textwrap.dedent(
            """
            import os, logging
            GLOBAL = 0
            def side_effecty(x):
                global GLOBAL
                if x > 0:
                    GLOBAL += 1
                    os.system("echo hi")
                    logging.info("done")
                    return x * 2
                return x
            def pure_calc(a, b):
                if a > b:
                    return a - b
                return b - a
            def writer(path, data):
                with open(path, "w") as f:
                    f.write(data)
                if data:
                    logging.warning(data)
                return len(data)
            """
        ),
        "app/util.py": textwrap.dedent(
            """
            import os
            def fetch(url):
                if url:
                    os.environ["X"] = url
                    return os.getcwd()
                return None
            def helper(n):
                total = 0
                for i in range(n):
                    if i % 2:
                        total += i
                return total
            """
        ),
        "app/empty.py": "x = 1\n",
        "tests/test_core.py": textwrap.dedent(
            """
            from app.core import pure_calc
            def test_pure_calc():
                assert pure_calc(3, 1) == 2
            """
        ),
        "tests/test_util.py": textwrap.dedent(
            """
            from app.util import helper
            def test_helper():
                assert helper(4) == 4
            """
        ),
    }
    for rel, content in files.items():
        p = os.path.join(str(base), rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)


def _load_original():
    path = os.environ.get("APEX_PP_ORIG_SNAPSHOT")
    if not path or not os.path.exists(path):
        return None
    import sys

    spec = importlib.util.spec_from_file_location("_pp_orig_charn", path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so the snapshot's dataclasses resolve their own
    # __module__ (dataclasses.asdict relies on sys.modules[cls.__module__]).
    sys.modules["_pp_orig_charn"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("light", [True, False])
def test_profile_byte_identical_to_snapshot(tmp_path, light):
    orig = _load_original()
    if orig is None:
        pytest.skip("APEX_PP_ORIG_SNAPSHOT not set; byte-identical proof skipped")
    _build_tree(tmp_path)
    new_out = _serialize(ProjectProfiler(str(tmp_path)).profile(light=light))
    orig_out = _serialize(orig.ProjectProfiler(str(tmp_path)).profile(light=light))
    assert new_out == orig_out


@pytest.mark.parametrize("light", [True, False])
def test_impure_untested_field_matches_snapshot(tmp_path, light):
    orig = _load_original()
    if orig is None:
        pytest.skip("APEX_PP_ORIG_SNAPSHOT not set; field proof skipped")
    _build_tree(tmp_path)
    new_p = ProjectProfiler(str(tmp_path)).profile(light=light)
    orig_p = orig.ProjectProfiler(str(tmp_path)).profile(light=light)
    new_f = new_p.impure_untested_functions
    orig_f = orig_p.impure_untested_functions
    assert json.dumps(new_f, sort_keys=True) == json.dumps(orig_f, sort_keys=True)
    # The representative tree has at least one impure-untested function.
    assert any(f["function"].endswith("side_effecty") for f in new_f)


def test_scan_produces_expected_records(tmp_path):
    """End-to-end check of the live scan against a fixed expectation."""
    _build_tree(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    found = {f["function"].rsplit(".", 1)[-1] for f in profile.impure_untested_functions}
    # Impure + untested are reported; pure_calc (pure, tested) and helper
    # (pure, tested) are not.
    assert "side_effecty" in found
    assert "fetch" in found
    assert "writer" in found
    assert "pure_calc" not in found
    assert "helper" not in found
    # Deterministic ordering: most side-effects first, then module/function.
    keys = [
        (-len(f["side_effects"]), f["module"], f["function"])
        for f in profile.impure_untested_functions
    ]
    assert keys == sorted(keys)


# --- edge / empty paths of the extracted helpers -------------------------


def test_prepare_impure_module_skips_non_py_and_tests(tmp_path):
    prof = ProjectProfiler(str(tmp_path))

    class _Analyzer:
        def analyze_file(self, path):  # pragma: no cover - never reached
            raise AssertionError("should not analyze a skipped module")

    assert prof._prepare_impure_module("README.md", _Analyzer()) is None
    assert prof._prepare_impure_module("tests/test_x.py", _Analyzer()) is None


def test_prepare_impure_module_missing_file(tmp_path):
    prof = ProjectProfiler(str(tmp_path))

    class _Analyzer:
        def analyze_file(self, path):  # pragma: no cover
            raise AssertionError("unreadable file must short-circuit")

    assert prof._prepare_impure_module("app/does_not_exist.py", _Analyzer()) is None


def test_prepare_impure_module_syntax_error(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "broken.py").write_text("def (:\n", encoding="utf-8")
    prof = ProjectProfiler(str(tmp_path))

    class _Analyzer:
        def analyze_file(self, path):
            raise SyntaxError("boom")

    assert prof._prepare_impure_module("app/broken.py", _Analyzer()) is None


def test_prepare_impure_module_no_functions(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "data.py").write_text("X = 1\n", encoding="utf-8")
    prof = ProjectProfiler(str(tmp_path))

    class _Analyzer:
        def analyze_file(self, path):
            return []

    assert prof._prepare_impure_module("app/data.py", _Analyzer()) is None


def test_prepare_impure_module_ok(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    prof = ProjectProfiler(str(tmp_path))

    class _Analyzer:
        def analyze_file(self, path):
            return [{"name": "f", "purity": "pure"}]

    result = prof._prepare_impure_module("app/m.py", _Analyzer())
    assert result is not None
    source, fns = result
    assert "def f()" in source
    assert fns == [{"name": "f", "purity": "pure"}]


def test_impure_untested_hit_filters():
    hit = ProjectProfiler._impure_untested_hit

    def never(_name):
        return False

    def always(_name):
        return True

    # Pure functions are not hits.
    assert hit("app/m.py", {"name": "f", "purity": "pure"}, never) is None
    # Dunder methods are skipped even when impure.
    assert hit("app/m.py", {"name": "C.__init__", "purity": "impure"}, never) is None
    # Exercised impure functions are skipped.
    assert hit("app/m.py", {"name": "g", "purity": "impure"}, always) is None
    # Impure, non-dunder, untested -> a record with copied side_effects.
    se = ["os.system"]
    record = hit(
        "app/m.py",
        {"name": "g", "purity": "impure", "lineno": 7, "side_effects": se},
        never,
    )
    assert record == {
        "module": "app/m.py",
        "function": "g",
        "line": 7,
        "side_effects": ["os.system"],
    }
    # side_effects is a copy, not the same list object.
    assert record["side_effects"] is not se
