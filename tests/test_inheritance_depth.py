"""Tests for the deterministic DIT (inheritance-depth) analyzer."""

from __future__ import annotations

from pathlib import Path

from app.tools.inheritance_depth import (
    InheritanceDepth,
    analyze_inheritance_depth,
)


def _write(root: Path, name: str, source: str) -> None:
    (root / name).write_text(source, encoding="utf-8")


def _find(records: list[dict], classname: str) -> dict | None:
    for r in records:
        if r["classname"] == classname:
            return r
    return None


def test_four_level_chain_depth_and_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "chain.py",
        "class A: pass\n"
        "class B(A): pass\n"
        "class C(B): pass\n"
        "class D(C): pass\n",
    )
    result = analyze_inheritance_depth(tmp_path)
    assert isinstance(result, InheritanceDepth)

    # A=0, B=1, C=2, D=3 edges. Default max_depth=4 -> D NOT flagged at depth 3.
    assert result.max_depth == 3
    assert _find(result.deep_classes, "D") is None
    # Confirm the exact depth when the threshold is lowered.
    low = analyze_inheritance_depth(tmp_path, max_depth=0)
    assert _find(low.deep_classes, "D")["depth"] == 3


def test_four_level_chain_flagged_with_threshold(tmp_path: Path) -> None:
    # A<-B<-C<-D gives D depth 3 (edges). Add E to reach depth 4 and flag it.
    _write(
        tmp_path,
        "chain.py",
        "class A: pass\n"
        "class B(A): pass\n"
        "class C(B): pass\n"
        "class D(C): pass\n"
        "class E(D): pass\n",
    )
    result = analyze_inheritance_depth(tmp_path)
    assert result.max_depth == 4

    flagged = _find(result.deep_classes, "E")
    assert flagged is not None
    assert flagged["depth"] == 4
    assert flagged["bases"] == ["D"]
    # D at depth 3 is below the default threshold of 4 -> not flagged.
    assert _find(result.deep_classes, "D") is None


def test_flat_class_depth_zero(tmp_path: Path) -> None:
    _write(tmp_path, "flat.py", "class Solo: pass\n")
    result = analyze_inheritance_depth(tmp_path)
    assert result.class_count == 1
    assert result.max_depth == 0
    assert result.mean_depth == 0.0
    assert result.deep_classes == []


def test_external_base_is_depth_one_leaf(tmp_path: Path) -> None:
    # Unknown/stdlib base does not contribute depth.
    _write(
        tmp_path,
        "ext.py",
        "import enum\n"
        "class Color(enum.Enum): pass\n"
        "class Sub(Color): pass\n",
    )
    result = analyze_inheritance_depth(tmp_path)
    color = _find(result.multi_inheritance, "Color")
    assert color is None  # only one base
    # Color: external base -> depth 0. Sub: resolves Color -> depth 1.
    depths = {c["classname"]: c["depth"] for c in result.deep_classes}
    # With max_depth lowered, verify exact depths.
    low = analyze_inheritance_depth(tmp_path, max_depth=0)
    depths = {c["classname"]: c["depth"] for c in low.deep_classes}
    assert depths["Color"] == 0
    assert depths["Sub"] == 1


def test_multiple_inheritance_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "multi.py",
        "class M1: pass\n"
        "class M2: pass\n"
        "class M3: pass\n"
        "class Combined(M1, M2, M3): pass\n",
    )
    result = analyze_inheritance_depth(tmp_path)
    combined = _find(result.multi_inheritance, "Combined")
    assert combined is not None
    assert sorted(combined["bases"]) == ["M1", "M2", "M3"]
    assert len(combined["bases"]) >= 3
    # Two bases should NOT be flagged.
    _write(tmp_path, "two.py", "class Pair(M1, M2): pass\n")
    result2 = analyze_inheritance_depth(tmp_path)
    assert _find(result2.multi_inheritance, "Pair") is None


def test_base_cycle_handled_without_infinite_loop(tmp_path: Path) -> None:
    # Name-based resolution can manufacture A(B) / B(A) cycle.
    _write(
        tmp_path,
        "cycle.py",
        "class A(B): pass\n"
        "class B(A): pass\n",
    )
    # Must terminate and stay bounded.
    result = analyze_inheritance_depth(tmp_path)
    assert isinstance(result, InheritanceDepth)
    assert result.class_count == 2
    # Depths are finite and bounded by class count (the cycle guard stops the
    # walk instead of recursing forever); determinism still holds.
    low = analyze_inheritance_depth(tmp_path, max_depth=0)
    depths = {c["classname"]: c["depth"] for c in low.deep_classes}
    assert all(d < result.class_count + 1 for d in depths.values())
    assert low == analyze_inheritance_depth(tmp_path, max_depth=0)


def test_self_referential_base_handled(tmp_path: Path) -> None:
    _write(tmp_path, "selfref.py", "class A(A): pass\n")
    result = analyze_inheritance_depth(tmp_path, max_depth=0)
    a = _find(result.deep_classes, "A")
    assert a is not None
    assert a["depth"] == 0


def test_empty_project_is_safe(tmp_path: Path) -> None:
    result = analyze_inheritance_depth(tmp_path)
    assert result == InheritanceDepth()
    assert result.deep_classes == []
    assert result.multi_inheritance == []
    assert result.max_depth == 0
    assert result.mean_depth == 0.0
    assert result.class_count == 0


def test_no_classes_only_functions(tmp_path: Path) -> None:
    _write(tmp_path, "funcs.py", "def f():\n    return 1\n")
    result = analyze_inheritance_depth(tmp_path)
    assert result == InheritanceDepth()


def test_test_files_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "real.py", "class Real: pass\n")
    _write(tmp_path, "test_thing.py", "class FakeBase: pass\n")
    (tmp_path / "tests").mkdir()
    _write(tmp_path / "tests", "helper.py", "class InTests: pass\n")
    result = analyze_inheritance_depth(tmp_path)
    names = {c["classname"] for c in result.deep_classes}
    # Lower threshold to surface every class.
    low = analyze_inheritance_depth(tmp_path, max_depth=0)
    names = {c["classname"] for c in low.deep_classes}
    assert "Real" in names
    assert "FakeBase" not in names
    assert "InTests" not in names
    assert result.class_count == 1


def test_determinism(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "class A: pass\n"
        "class B(A): pass\n"
        "class C(B): pass\n"
        "class D(C): pass\n"
        "class E(D): pass\n",
    )
    _write(
        tmp_path,
        "b.py",
        "class X1: pass\n"
        "class X2: pass\n"
        "class X3: pass\n"
        "class Wide(X1, X2, X3): pass\n",
    )
    first = analyze_inheritance_depth(tmp_path)
    second = analyze_inheritance_depth(tmp_path)
    assert first == second
    assert first.deep_classes == second.deep_classes
    assert first.multi_inheritance == second.multi_inheritance


def test_deep_classes_sorted_and_capped(tmp_path: Path) -> None:
    # Build a long chain so cap/order are exercised.
    lines = ["class C0: pass\n"]
    for n in range(1, 25):
        lines.append(f"class C{n}(C{n - 1}): pass\n")
    _write(tmp_path, "deep.py", "".join(lines))
    result = analyze_inheritance_depth(tmp_path)
    assert len(result.deep_classes) <= 15
    depths = [c["depth"] for c in result.deep_classes]
    assert depths == sorted(depths, reverse=True)
    assert result.max_depth == 24
