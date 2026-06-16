"""Tests for the WIDENED simplification-scanner coverage.

This wave deepens the develop-loop's discovery end by teaching
:func:`scan_simplifications` to dry-run one more safe, already-implemented,
bridge-executable transform — the ``mutable-default`` fix
(``def f(x=[])`` -> sentinel ``def f(x=None): if x is None: x = []``).

These tests pin three things:

  * the new transform is detected with the EXACT executable fact-label the
    bridge's ``_FACT_ACTIONS`` routes to ``fix_mutable_defaults``;
  * it dry-runs cleanly (never raises a TypeError from a signature mismatch)
    and correctly returns NOTHING on a file with no mutable default;
  * the scan stays a DETERMINISTIC SUPERSET — adding the transform never
    reorders or drops a previously-returned opportunity, and a tree with no
    new opportunity yields byte-identical output.
"""

from app.engine.idea_action_bridge import _FACT_ACTIONS
from app.tools.simplification_scan import scan_simplifications

# The footgun the new coverage fires on, and its already-fixed sentinel form.
_POSITIVE = "def f(x=[]):\n    return x\n"
_NEGATIVE = "def g(y=None):\n    if y is None:\n        y = []\n    return y\n"


# --- new coverage: mutable-default -----------------------------------------

def test_scanner_detects_mutable_default(tmp_path):
    (tmp_path / "m.py").write_text(_POSITIVE, encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    labels = {o["fact_label"] for o in opps}
    assert "mutable-default" in labels
    hit = next(o for o in opps if o["fact_label"] == "mutable-default")
    assert hit["module"] == "m.py"
    assert hit["transform"] == "mutable_default"


def test_mutable_default_fact_label_is_executable():
    # The scanner is only honest if its emitted label routes to a REAL apply.
    assert "mutable-default" in _FACT_ACTIONS
    action_type, _desc, executable = _FACT_ACTIONS["mutable-default"]
    assert executable is True
    assert action_type == "fix_mutable_defaults"


def test_scanner_mutable_default_negative_yields_nothing(tmp_path):
    # A function whose default is already the sentinel must NOT be flagged —
    # the transform refuses (None) so no opportunity is fabricated.
    (tmp_path / "clean.py").write_text(_NEGATIVE, encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    assert not any(o["fact_label"] == "mutable-default" for o in opps)


def test_scanner_mutable_default_dry_run_does_not_raise(tmp_path):
    # The transform is a pure 3-arg apply; the scan must never surface a
    # TypeError as a hollow "opportunity". Mixing a positive and a clean file
    # exercises both the fire and the refuse path in one walk.
    (tmp_path / "m.py").write_text(_POSITIVE, encoding="utf-8")
    (tmp_path / "clean.py").write_text(_NEGATIVE, encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    hits = [o for o in opps if o["fact_label"] == "mutable-default"]
    assert [o["module"] for o in hits] == ["m.py"]


# --- determinism / superset invariants -------------------------------------

def test_scan_is_deterministic(tmp_path):
    (tmp_path / "m.py").write_text(_POSITIVE, encoding="utf-8")
    (tmp_path / "n.py").write_text("def h(x):\n    return not not x\n", encoding="utf-8")
    assert scan_simplifications(tmp_path) == scan_simplifications(tmp_path)


def test_scan_sorted_by_module_then_label(tmp_path):
    # Two distinct modules each with a fireable transform -> output is sorted
    # by (module, fact_label), the contract the downstream budget relies on.
    (tmp_path / "b_mod.py").write_text(_POSITIVE, encoding="utf-8")
    (tmp_path / "a_mod.py").write_text("def h(x):\n    return not not x\n", encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    keys = [(o["module"], o["fact_label"]) for o in opps]
    assert keys == sorted(keys)


def test_no_new_opportunity_yields_empty(tmp_path):
    # A tree with no mutable default AND no other fireable transform must stay
    # empty: the widened coverage only ADDS detections, never invents one.
    (tmp_path / "clean.py").write_text(_NEGATIVE, encoding="utf-8")
    assert scan_simplifications(tmp_path) == []


def test_existing_transforms_still_detected(tmp_path):
    # Superset proof at the unit level: a previously-covered transform
    # (double-not) is still detected after the widening, unaffected by the
    # new mutable-default pair sharing the same scan.
    (tmp_path / "m.py").write_text("def f(x):\n    return not not x\n", encoding="utf-8")
    labels = {o["fact_label"] for o in scan_simplifications(tmp_path)}
    assert "double-not" in labels
