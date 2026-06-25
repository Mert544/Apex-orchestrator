"""The ``LanguageAdapter`` seam — the four-verb structural plug-in that turns
Apex from a Python-only develop agent into a multi-language one (Python stays
byte-identical, off-by-default).

These tests pin the seam's CONTRACTS, not new behaviour:

* the registry dispatches a file to the right adapter, deterministically, Python
  first (so ``.py`` always resolves to the off-by-default :class:`PythonAdapter`);
* the :class:`JavaScriptAdapter` is byte-for-byte equivalent to the legacy JS
  predicates/splice it was extracted from (the extraction-equivalence contract);
* the :class:`PythonAdapter`'s file gate equals the existing
  ``.py``+fixture+non-library filter (delegation-equivalence — this is what LOCKS
  the off-by-default byte-identity of the Python path as a checked contract);
* parse/reparses REFUSE (never guess) on an unparseable source;
* importing the seam forms no app import cycle, and the single gated writer
  (``apply_rename``) invariant is untouched by the new package.

The one heavy assertion — the JS driver re-parse proof — skips cleanly when
node + a global ``typescript`` are unavailable, exactly as the js-tdd-implement
pin does; every pure contract test always runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.lang import (
    adapter_for,
    adapters,
    clear_registry,
)
from app.execution.lang.adapter import (
    Edit,
    LanguageAdapter,
    Target,
    TargetQuery,
)
from app.execution.lang.js_adapter import (
    JavaScriptAdapter,
    _splice_body,
    is_js_source,
)
from app.execution.lang.python_adapter import PythonAdapter
from app.execution.js.js_tool import JsStub, global_node_modules


def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the LLM-free driver re-parse proof to run (mirrors the
    js-tdd-implement pin's guard)."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_needs_node = pytest.mark.skipif(not _node_ok(),
                                 reason="node + global typescript not available")


# Representative paths exercising every JS/TS suffix, the Python gate, and the
# refused (test/other-language) cases.
_JS_PATHS = ["a/m.js", "x.mjs", "y.cjs", "c.jsx", "src/util.ts", "d.tsx"]
_PY_PATHS = ["m.py", "app/core/widget.py", "pkg/sub/mod.py"]
_REFUSED = ["a/m.test.js", "a.spec.ts", "__tests__/math.js", "x.txt", "data.json"]


def test_registry_python_first_and_owns_dispatch():
    # adapter_for routes each file to the owning adapter, Python first, and refuses
    # (None) a file no adapter claims. Registry order is deterministic.
    assert adapter_for("m.py").name == "python"
    for rel in _JS_PATHS:
        assert adapter_for(rel).name == "javascript", rel
    # a jest test file and a non-source file belong to no adapter
    assert adapter_for("a/m.test.js") is None
    assert adapter_for("x.txt") is None
    # the order is exactly [python, <rest sorted>]; Python leads by construction
    names = [a.name for a in adapters()]
    assert names[0] == "python"
    assert "javascript" in names
    assert names == sorted(names, key=lambda n: (0 if n == "python" else 1, n))
    # deterministic across calls
    assert [a.name for a in adapters()] == names


def test_clear_registry_reloads_builtins_deterministically():
    # clearing then re-reading rebuilds the same built-in set in the same order
    before = [a.name for a in adapters()]
    clear_registry()
    after = [a.name for a in adapters()]
    assert after == before
    assert {"python", "javascript"} <= set(after)


def test_js_adapter_owns_matches_legacy_predicate():
    # The extraction-equivalence contract: JavaScriptAdapter.owns(rel) is exactly
    # the legacy is_js_source(rel), byte-for-byte, over every shape.
    js = JavaScriptAdapter()
    for rel in _JS_PATHS + _PY_PATHS + _REFUSED:
        assert js.owns(rel) == is_js_source(rel), rel


def test_js_adapter_apply_equals_legacy_splice():
    # For a representative source + JsStub + body, JavaScriptAdapter.apply(...)
    # equals the legacy _splice_body(...) output exactly.
    source = 'function add(a, b) {\n  throw new Error("x");\n}\n'
    start = source.index("{")
    end = source.index("}") + 1
    stub = JsStub(name="add", params=("a", "b"), body_start=start, body_end=end)
    body = "return a + b;"

    js = JavaScriptAdapter()
    target = js.locate(js.parse(source), source,
                       TargetQuery(name="add", extra={"stub": stub}))
    assert target == Target(name="add", span=(start, end))
    via_adapter = js.apply(source, target, Edit(body=body))
    via_legacy = _splice_body(source, stub, body)
    assert via_adapter == via_legacy
    assert via_adapter == f"function add(a, b) {{ {body} }}\n"


def test_js_adapter_apply_refuses_out_of_range_span():
    # An out-of-range span returns None (both the adapter and the legacy splice) —
    # refuse rather than corrupt the file.
    source = "function f(a) { throw 1; }\n"
    bad = Target(name="f", span=(0, len(source) + 5))
    js = JavaScriptAdapter()
    assert js.apply(source, bad, Edit(body="return a;")) is None
    stub = JsStub(name="f", params=("a",), body_start=0, body_end=len(source) + 5)
    assert _splice_body(source, stub, "return a;") is None


def test_js_adapter_locate_refuses_unknown_symbol():
    # locate returns None when the query names a symbol the supplied stub is not.
    source = "function f(a) { throw 1; }\n"
    stub = JsStub(name="f", params=("a",), body_start=14, body_end=25)
    js = JavaScriptAdapter()
    assert js.locate(js.parse(source), source,
                     TargetQuery(name="other", extra={"stub": stub})) is None
    # and when no stub hint is supplied at all
    assert js.locate(js.parse(source), source, TargetQuery(name="f")) is None


def _python_gate(rel: str) -> bool:
    """The exact filter the existing Python single-file path enforces, inlined
    here as the reference the PythonAdapter must match."""
    from app.execution._transform_base import is_fixture_path
    from app.execution.cross_file_rename import _is_non_library_file

    return (rel.endswith(".py")
            and not is_fixture_path(rel)
            and not _is_non_library_file(rel))


def test_python_adapter_owns_matches_existing_filter():
    # Delegation-equivalence: PythonAdapter.owns(rel) == the existing
    # .py + fixture + non-library filter over a sample (this LOCKS the
    # off-by-default byte-identity of the Python path as a checked contract).
    py = PythonAdapter()
    sample = (_PY_PATHS + _JS_PATHS + _REFUSED
              + ["setup.py", "docs/conf.py", "conftest.py", "noxfile.py",
                 "tests/test_x.py", "fixtures/data.py", "examples/demo.py",
                 "app/intent/parser.py"])
    for rel in sample:
        assert py.owns(rel) == _python_gate(rel), rel
    # spot the load-bearing cases
    assert py.owns("app/core/widget.py") is True
    assert py.owns("setup.py") is False         # non-library
    assert py.owns("tests/test_x.py") is False  # fixture/test
    assert py.owns("x.js") is False             # wrong language


def test_python_adapter_parse_locate_apply_roundtrip():
    # The Python delegator can parse, locate a top-level def's byte span, splice
    # it, and the result re-parses — a pure-bytes round trip (off-by-default path).
    source = "def f(a):\n    return 1\n\n\ndef g(b):\n    return b\n"
    py = PythonAdapter()
    tree = py.parse(source)
    assert tree is not None
    target = py.locate(tree, source, TargetQuery(name="g"))
    assert target is not None and target.name == "g"
    assert source[target.span[0]:target.span[1]] == "def g(b):\n    return b"
    spliced = py.apply(source, target, Edit(body="def g(b):\n    return b + 1"))
    assert spliced == "def f(a):\n    return 1\n\n\ndef g(b):\n    return b + 1\n"
    assert py.reparses(spliced) is True


def test_python_adapter_locate_refuses_ambiguous_or_absent():
    # Zero or many definitions of a name -> None (refuse, never guess).
    py = PythonAdapter()
    dup = "def f():\n    return 1\n\n\ndef f():\n    return 2\n"
    assert py.locate(py.parse(dup), dup, TargetQuery(name="f")) is None
    one = "def f():\n    return 1\n"
    assert py.locate(py.parse(one), one, TargetQuery(name="missing")) is None


def test_parse_and_reparses_refuse_on_unparseable():
    # PythonAdapter.parse is None and reparses False on broken Python — the
    # never-guess refusal that makes the seam verified-or-refused.
    py = PythonAdapter()
    broken = "def f(:\n    return\n"
    assert py.parse(broken) is None
    assert py.reparses(broken) is False
    # well-formed Python re-parses
    assert py.reparses("x = 1\n") is True


@_needs_node
def test_js_reparses_refuses_unparseable_driver_exit2():
    # JavaScriptAdapter.reparses is False on a file the TS driver exits-2 on
    # (does-not-parse), True on valid JS — the JS image of the ast.parse guard.
    js = JavaScriptAdapter()
    assert js.reparses("function ( {\n") is False
    assert js.reparses("function ok(a) { return a + 1; }\n") is True


def test_adapters_satisfy_the_protocol_structurally():
    # Both built-ins are structural LanguageAdapters (runtime_checkable Protocol),
    # so a new language is a plug-in, not a subclass.
    for a in adapters():
        assert isinstance(a, LanguageAdapter), a
    assert isinstance(PythonAdapter(), LanguageAdapter)
    assert isinstance(JavaScriptAdapter(), LanguageAdapter)


def test_no_import_cycle_and_single_writer_intact():
    # Importing the seam forms no app import cycle, and the single gated writer
    # invariant (apply_rename is the SOLE writer) is untouched after the rewrite.
    import importlib

    for mod in ("app.execution.lang",
                "app.execution.lang.adapter",
                "app.execution.lang.js_adapter",
                "app.execution.lang.python_adapter"):
        importlib.import_module(mod)  # imports cleanly, no cycle

    from app.engine.soundness_audit import check_single_writer, repo_root

    ok, offenders = check_single_writer(repo_root())
    assert ok is True
    assert offenders == []


def test_lang_modules_do_not_call_apply_rename():
    # Structural guard: no module under app/execution/lang calls apply_rename, so
    # the gated-writer count (exactly one call site) is preserved.
    from app.engine.soundness_audit import repo_root

    lang_dir = Path(repo_root()) / "app" / "execution" / "lang"
    for path in sorted(lang_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "apply_rename(" not in text, f"{path} must not call apply_rename"


def test_north_star_and_soundness_audits_still_pass():
    # No new objective registered -> no parity gap; both RAISE-on-drift audits
    # stay PASS with the seam wired in.
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    assert north_star_report(".")["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []
