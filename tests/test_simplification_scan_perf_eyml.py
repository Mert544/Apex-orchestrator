"""Performance + correctness gate for the in-memory simplification dry-run.

``scan_simplifications`` used to run each on-disk ``plan_<name>(root, rel)``
transform by materialising the source into a fresh ``tempfile.TemporaryDirectory``
and letting the transform re-read + re-``ast.parse`` it from disk — once per
(file x transform), ~36 re-parses per file, none cached. That temp-dir +
disk-write + re-parse is the dominant constant in ``ProjectProfiler.profile()``.

The fix routes those transforms through ``_plan_transforms.plan_from_source``,
which supplies the source IN MEMORY via ``_transform_base.source_override`` so the
transform runs its IDENTICAL collect -> apply -> re-parse -> build-plan path on the
provided string with no filesystem at all.

This module proves two things, both non-negotiable for a proof-carrying engine:

  1. BYTE-IDENTICAL output. The in-memory ``plan_from_source`` route and a
     reference temp-dir route (the exact old behaviour, reconstructed here) yield
     the same ``RenamePlan`` for every transform on hand-built triggering and
     non-triggering sources, and ``scan_simplifications`` returns identical output
     on synthetic trees and the real repo.
  2. ZERO TEMP-DIR I/O. On a generated ~300-file synthetic repo, the in-memory
     scan creates no temp dirs, writes no files, and reads each file exactly
     once, while the reference temp-dir scan pays per (file x transform) —
     proven by counting shims, not by timing (P4:
     docs/rnd/context-fragile-tests.md finding #1).

Deterministic: no clock in any assertion, no randomness, fixed sources.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.engine.skip_dirs import iter_source_files
from app.execution import _plan_transforms as _pt
from app.tools.simplification_scan import (
    _DRY_RUN_TITLE,
    _transforms,
    plan_to_apply,
    scan_simplifications,
)


# --- reference: the EXACT old temp-dir dry-run, reconstructed -----------------

def _reference_plan_to_apply(plan_fn):
    """The pre-change ``plan_to_apply._apply``: mirror source into a throwaway
    temp dir at ``rel`` and let the on-disk transform re-read + re-parse it.

    Kept here verbatim (modulo imports) as the BASELINE the in-memory route must
    match byte-for-byte, so the proof does not depend on a checked-out old copy."""
    def _apply(rel_path: str, source: str, _title: str):
        from app.execution.semantic.result import SemanticPatchResult

        rel = Path(rel_path).as_posix()
        try:
            with tempfile.TemporaryDirectory() as droot:
                fpath = Path(droot) / rel
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(source, encoding="utf-8")
                plan = plan_fn(droot, rel)
        except Exception:
            return None
        if not getattr(plan, "ok", False):
            return None
        new_content = plan.new_contents.get(rel)
        if new_content is None or new_content == source:
            return None
        edits = plan.edits_by_file.get(rel, 1)
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": new_content,
                "expected_old_content": source,
            }],
            transform_type=plan.new,
            rationale=[
                f"Applied {edits} behaviour-preserving {plan.new} "
                f"simplification(s) in {rel_path}."
            ],
        )

    return _apply


# Every on-disk ``plan_<name>`` the scanner wires through ``plan_to_apply``.
_PLAN_FNS = {
    "nested_with": _pt.plan_combine_nested_with,
    "comprehension": _pt.plan_simplify_comprehension,
    "use_enumerate": _pt.plan_use_enumerate,
    "len_comparison": _pt.plan_simplify_len_comparison,
    "bool_return": _pt.plan_simplify_bool_return,
    "ternary_bool": _pt.plan_simplify_ternary_bool,
    "dict_get": _pt.plan_simplify_dict_get,
    "dict_comprehension": _pt.plan_dict_comprehension,
    "negated_comparison": _pt.plan_simplify_negated_comparison,
    "pointless_pass": _pt.plan_remove_pointless_pass,
    "assert_tuple": _pt.plan_fix_assert_tuple,
    "bool_comparison": _pt.plan_simplify_bool_comparison,
}

# Sources that TRIGGER each plan transform (one each) — the "would act" path.
_TRIGGERS = {
    "nested_with": "def f():\n    with a() as x:\n        with b() as y:\n            pass\n",
    "comprehension": "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n",
    "use_enumerate": "def f(seq):\n    for i in range(len(seq)):\n        print(seq[i])\n",
    "len_comparison": "def f(x):\n    if len(x) == 0:\n        return 1\n    return 2\n",
    "bool_return": "def f(c):\n    if c:\n        return True\n    else:\n        return False\n",
    "ternary_bool": "def f(c):\n    return True if c else False\n",
    "dict_get": "def f(d, k):\n    return d[k] if k in d else 0\n",
    "dict_comprehension": "def f(xs):\n    out = {}\n    for x in xs:\n        out[x] = x\n    return out\n",
    "negated_comparison": "def f(a, b):\n    return not a < b\n",
    "pointless_pass": "def f():\n    pass\n    return 1\n",
    "assert_tuple": 'def f(c):\n    assert (c, "msg")\n',
    "bool_comparison": "def f(a, b):\n    return (a < b) == True\n",
}

# A clean source no plan transform acts on — the "refuse" (None) path.
_CLEAN = "def f(x):\n    return x + 1\n"

# A syntactically broken source — every transform must refuse identically.
_BROKEN = "def f(:\n    return\n"


@pytest.mark.parametrize("name", sorted(_PLAN_FNS))
def test_in_memory_plan_matches_temp_dir_on_trigger(name):
    """Triggering source: in-memory plan == temp-dir plan, attribute-for-attribute."""
    plan_fn = _PLAN_FNS[name]
    source = _TRIGGERS[name]
    rel = "pkg/mod.py"
    mem = _pt.plan_from_source(plan_fn, rel, source)
    with tempfile.TemporaryDirectory() as droot:
        p = Path(droot) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(source, encoding="utf-8")
        disk = plan_fn(droot, rel)
    assert mem.ok and disk.ok, f"{name} should fire on its trigger"
    assert mem.new == disk.new
    assert mem.new_contents == disk.new_contents
    assert mem.originals == disk.originals
    assert mem.edits_by_file == disk.edits_by_file
    assert mem.blockers == disk.blockers


@pytest.mark.parametrize("name", sorted(_PLAN_FNS))
@pytest.mark.parametrize("source", [_CLEAN, _BROKEN], ids=["clean", "broken"])
def test_in_memory_plan_matches_temp_dir_on_refuse(name, source):
    """Clean and broken sources: both routes refuse identically (same blockers)."""
    plan_fn = _PLAN_FNS[name]
    rel = "pkg/mod.py"
    mem = _pt.plan_from_source(plan_fn, rel, source)
    with tempfile.TemporaryDirectory() as droot:
        p = Path(droot) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(source, encoding="utf-8")
        disk = plan_fn(droot, rel)
    assert mem.ok == disk.ok
    assert mem.new_contents == disk.new_contents
    assert mem.blockers == disk.blockers


@pytest.mark.parametrize("name", sorted(_PLAN_FNS))
def test_apply_adapter_matches_reference_temp_dir(name):
    """The scanner's ``plan_to_apply`` (in-memory) returns the SAME SemanticPatchResult
    as the reconstructed temp-dir reference, for both trigger and clean inputs."""
    plan_fn = _PLAN_FNS[name]
    in_mem = plan_to_apply(plan_fn)
    reference = _reference_plan_to_apply(plan_fn)
    for source in (_TRIGGERS[name], _CLEAN, _BROKEN):
        rel = "pkg/mod.py"
        got = in_mem(rel, source, _DRY_RUN_TITLE)
        ref = reference(rel, source, _DRY_RUN_TITLE)
        if ref is None:
            assert got is None
        else:
            assert got is not None
            assert got.patch_requests == ref.patch_requests
            assert got.transform_type == ref.transform_type
            assert got.rationale == ref.rationale


def _build_synthetic_repo(root: Path, n_files: int) -> None:
    """Generate ``n_files`` deterministic .py files, a mix of triggering and clean.

    Pure: file ``i`` always gets the same content, so the scan output and the
    benchmark are reproducible."""
    triggers = list(_TRIGGERS.values())
    for i in range(n_files):
        # Every 3rd file triggers a (rotating) transform; the rest are clean — a
        # realistic ratio that keeps the scan output capped + stable.
        if i % 3 == 0:
            body = triggers[i % len(triggers)]
        else:
            body = f"def f_{i}(x):\n    return x + {i}\n"
        (root / f"mod_{i:04d}.py").write_text(body, encoding="utf-8")


def test_scan_byte_identical_on_synthetic_trees(tmp_path):
    """``scan_simplifications`` is byte-identical to a reference scan that uses the
    temp-dir adapter, on two distinct synthetic trees."""
    for size in (30, 120):
        repo = tmp_path / f"repo_{size}"
        repo.mkdir()
        _build_synthetic_repo(repo, size)

        live = scan_simplifications(repo)
        # Reference scan: same pipeline, but every plan-based transform routed
        # through the reconstructed temp-dir adapter.
        ref = _reference_scan(repo)
        assert json.dumps(live, sort_keys=True) == json.dumps(ref, sort_keys=True)


def _reference_scan(root: Path) -> list[dict]:
    """A from-scratch scan that uses the temp-dir reference adapter for every
    plan-based transform — the pre-change behaviour, end to end."""
    import app.tools.simplification_scan as ss

    # Rebuild the transform list, substituting the reference temp-dir adapter for
    # the in-memory one on each plan-based transform.
    plan_label_to_fn = {
        "nested-with": _pt.plan_combine_nested_with,
        "comprehension": _pt.plan_simplify_comprehension,
        "use-enumerate": _pt.plan_use_enumerate,
        "len-comparison": _pt.plan_simplify_len_comparison,
        "simplify-bool-return": _pt.plan_simplify_bool_return,
        "ternary-bool": _pt.plan_simplify_ternary_bool,
        "dict-get-ternary": _pt.plan_simplify_dict_get,
        "dict-comprehension": _pt.plan_dict_comprehension,
        "ordering-negation": _pt.plan_simplify_negated_comparison,
        "pointless-pass": _pt.plan_remove_pointless_pass,
        "assert-tuple": _pt.plan_fix_assert_tuple,
        "bool-comparison": _pt.plan_simplify_bool_comparison,
    }
    transforms = []
    for label, apply in _transforms():
        if label in plan_label_to_fn:
            transforms.append((label, _reference_plan_to_apply(plan_label_to_fn[label])))
        else:
            transforms.append((label, apply))

    files = [
        p for p in iter_source_files(root, "*.py")
        if not ss._is_excluded(str(p.relative_to(root)))
    ]
    opportunities: list[dict] = []
    for path in files:
        rel = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for fact_label, apply in transforms:
            try:
                result = apply(rel, source, _DRY_RUN_TITLE)
            except Exception:
                result = None
            if result is not None:
                opportunities.append({
                    "module": rel,
                    "transform": fact_label.replace("-", "_"),
                    "fact_label": fact_label,
                })
    opportunities.sort(key=lambda o: (o["module"], o["fact_label"]))
    return opportunities[:ss._MAX_OPPORTUNITIES]


def test_in_memory_scan_is_faster_than_temp_dir(tmp_path, monkeypatch):
    """On a ~300-file synthetic repo, the in-memory scan performs ZERO temp-dir
    filesystem work while the temp-dir reference pays per (file x plan-transform)
    — with byte-identical output.

    P4 (docs/rnd/context-fragile-tests.md finding #1): this used to time both
    scans and assert a >=1.5x wall-clock speedup ratio, which could dip below
    the floor under gate load with zero code change. The counters below pin the
    exact invariant the speedup comes FROM — the in-memory route creates no
    temp dirs, writes no files, and reads each file exactly once — so the test
    still fails on the same regression (the scan silently falling back to
    temp-dir I/O) while never consulting a clock. STRICTER than the old ratio:
    zero recomputation, not merely "faster"."""
    repo = tmp_path / "repo300"
    repo.mkdir()
    _build_synthetic_repo(repo, 300)

    # Warm both routes once BEFORE arming the counters, so any lazy first-call
    # initialisation inside the transforms never pollutes the counted runs.
    scan_simplifications(repo)

    counts = {"tempdirs": 0, "writes": 0, "reads": 0}
    real_tempdir = tempfile.TemporaryDirectory
    real_write_text = Path.write_text
    real_read_text = Path.read_text

    def counting_tempdir(*args, **kwargs):
        counts["tempdirs"] += 1
        return real_tempdir(*args, **kwargs)

    def counting_write_text(self, *args, **kwargs):
        counts["writes"] += 1
        return real_write_text(self, *args, **kwargs)

    def counting_read_text(self, *args, **kwargs):
        counts["reads"] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", counting_tempdir)
    monkeypatch.setattr(Path, "write_text", counting_write_text)
    monkeypatch.setattr(Path, "read_text", counting_read_text)

    live = scan_simplifications(repo)
    mem = dict(counts)

    ref = _reference_scan(repo)
    ref_tempdirs = counts["tempdirs"] - mem["tempdirs"]
    ref_writes = counts["writes"] - mem["writes"]
    ref_reads = counts["reads"] - mem["reads"]

    # Equal output, exactly as before.
    assert json.dumps(live, sort_keys=True) == json.dumps(ref, sort_keys=True)

    # The in-memory scan: no temp dirs, no writes, ONE read per file (the
    # scanner's own read_text) — the transforms re-read NOTHING from disk.
    assert mem["tempdirs"] == 0
    assert mem["writes"] == 0
    assert mem["reads"] == 300

    # The reference route really pays per (file x plan-transform). This also
    # proves the counting shims intercept the temp-dir machinery, so the zeros
    # above can never be vacuously green.
    assert ref_tempdirs >= 300 * len(_PLAN_FNS)
    assert ref_writes >= 300 * len(_PLAN_FNS)
    assert ref_reads >= 300 + 300 * len(_PLAN_FNS)
