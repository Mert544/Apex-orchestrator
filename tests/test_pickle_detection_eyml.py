"""Pickle/marshal untrusted-deserialization detection (flag-only / human-review).

Red-teams found that ``pickle.load(...)`` / ``pickle.loads(...)`` on untrusted
input — RCE-on-load, the norm for ML model files — was never flagged by any
organ (scan, grade, readiness, ideate). These pin the new AST-based detection:

  - ``pickle.load(f)`` / ``pickle.loads(data)`` (file-stream and bytes forms),
    and the ``cPickle`` / ``_pickle`` module aliases, each produce a high-severity
    security finding via ``detect()`` (so ``apex grade`` counts it and
    ``security_labels`` reports it).
  - ``marshal.load`` / ``marshal.loads`` likewise (unsafe on untrusted input).
  - No false positives: benign ``pickle.dumps(...)`` (serialization, not load)
    and a comment/string mention of "pickle.load" are NOT flagged (AST-based,
    not substring).
  - The new ``.load`` / alias / marshal findings are FLAG-ONLY (fix_kind == "",
    no auto-fix routing) because there is no safe drop-in replacement; the
    legacy ``pickle.loads`` rule keeps its ``fix_kind == "pickle"`` routing.
  - Deterministic: same input -> identical findings.
"""

from __future__ import annotations

from app.engine.detectors import detect, security_label, security_labels


def _security(source: str):
    return [i for i in detect(source) if i.category == "security"]


# --- pickle.load / pickle.loads (and aliases) are flagged ---------------------

def test_pickle_load_file_stream_flagged():
    out = _security("import pickle\ndef f(fh):\n    return pickle.load(fh)\n")
    assert len(out) == 1
    issue = out[0]
    assert issue.severity == "high"
    assert "pickle" in issue.message and "arbitrary code" in issue.message
    # Flag-only: no auto-fix routing (no safe drop-in replacement).
    assert issue.fix_kind == "" and not issue.auto_fixable


def test_pickle_loads_bytes_still_flagged_via_legacy_rule():
    # The legacy pickle.loads rule wins (ordered first) and keeps its routing.
    out = _security("import pickle\npickle.loads(data)\n")
    assert len(out) == 1
    assert out[0].fix_kind == "pickle"
    assert out[0].severity == "high"


def test_cpickle_load_and_loads_flagged():
    for call in ("cPickle.load(fh)", "cPickle.loads(b)"):
        out = _security(f"import cPickle\n{call}\n")
        assert len(out) == 1, call
        assert out[0].severity == "high"
        # Aliases are flag-only (the loads transform only rewrites the `pickle` name).
        assert out[0].fix_kind == ""


def test_underscore_pickle_alias_flagged():
    out = _security("import _pickle\n_pickle.load(fh)\n")
    assert len(out) == 1
    assert out[0].severity == "high" and out[0].fix_kind == ""


def test_marshal_load_and_loads_flagged():
    for call in ("marshal.load(fh)", "marshal.loads(b)"):
        out = _security(f"import marshal\n{call}\n")
        assert len(out) == 1, call
        assert out[0].severity == "high"
        assert "marshal" in out[0].message and out[0].fix_kind == ""


# --- no false positives ------------------------------------------------------

def test_pickle_dumps_not_flagged():
    # Serialization (dumps/dump), not deserialization — safe, never flagged.
    assert _security("import pickle\npickle.dumps(x)\n") == []
    assert _security("import pickle\npickle.dump(x, fh)\n") == []


def test_pickle_mention_in_comment_not_flagged():
    src = "# pickle.load(fh) is dangerous; we avoid it\nx = 1\n"
    assert _security(src) == []


def test_pickle_mention_in_string_not_flagged():
    src = "msg = 'never call pickle.loads on untrusted data'\n"
    assert _security(src) == []


def test_json_loads_not_flagged():
    # attr is `loads` but the owner is json, not a pickle module.
    assert _security("import json\njson.loads(s)\n") == []


def test_marshal_dumps_not_flagged():
    assert _security("import marshal\nmarshal.dumps(x)\n") == []


# --- flows through detect() so grade counts it / security_labels reports it ---

def test_security_label_reports_legacy_pickle_loads():
    # loads (legacy, routed) participates in the severity-ordered label list.
    assert security_label("import pickle\npickle.loads(b)\n") == "pickle"
    assert "pickle" in security_labels("import pickle\npickle.loads(b)\n")


def test_pickle_load_counts_as_a_security_finding_for_grade():
    # Flag-only findings carry no fix_kind, so they are not in security_labels()
    # (which keys on fix_kind), but they DO surface as category=="security"
    # findings — exactly how grade counts them (like exec / hardcoded-secret).
    out = detect("import pickle\npickle.load(fh)\n")
    assert any(i.category == "security" and i.severity == "high" for i in out)
    # No routing label, mirroring the exec()/shell=True flag-only contract.
    assert security_labels("import pickle\npickle.load(fh)\n") == []


# --- determinism -------------------------------------------------------------

def test_detection_is_deterministic():
    src = (
        "import pickle, marshal, cPickle\n"
        "pickle.load(a)\n"
        "pickle.loads(b)\n"
        "cPickle.loads(c)\n"
        "marshal.load(d)\n"
    )
    first = detect(src)
    for _ in range(5):
        assert detect(src) == first


def test_kitchen_sink_pickle_load_does_not_double_count():
    # A single pickle.load call yields exactly one security finding (first
    # matching rule wins — no overlap between the legacy loads rule and the
    # broader load/alias rule).
    src = "import pickle\npickle.load(fh)\npickle.loads(b)\n"
    out = _security(src)
    assert len(out) == 2
    assert {i.line for i in out} == {2, 3}
