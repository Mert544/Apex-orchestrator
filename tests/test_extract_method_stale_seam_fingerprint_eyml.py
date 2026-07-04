"""Regression: ``plan_extract`` re-verifies a caller-supplied structural
fingerprint of the seam at APPLY time, refusing when the file drifted since
PLAN time instead of silently splicing whatever now occupies the stale line
range.

The hazard: ``suggest_extractions`` (PLAN time) and ``plan_extract`` (APPLY
time) both anchor a seam SOLELY by ``(start_line, end_line)``. In the
objective compiler's per-pass campaign (``_extract_moves`` -> ``Move.
build_plan``), a move's plan is built from line numbers captured against the
tree at the TOP of a pass, but the actual ``plan_extract`` call can run
several moves later — after an EARLIER move in the SAME pass already edited
the SAME file (``_run_pass``'s own documented scenario: "line numbers stay
exact even as earlier moves in the same pass edit the file"). ``plan_extract``
always re-reads the file fresh, so the stale line numbers still "resolve" to
SOME valid contiguous statement run — just not necessarily the one that was
scored. This is the extract-method sibling of the dedup family's stale-line
bug (fixed there by ``app.execution._dedup_helpers._identity_blocker``): same
family (a stale detector position silently rewrites the WRONG code), applied
here across TIME instead of across occurrences.

Frozen repro: a live probe driving the real, unmocked ``suggest_extractions``
-> ``plan_extract`` -> ``apply_rename`` chain with a hand-staled plan (plan
built against version A, applied after the file drifted to version B)
confirmed the PRE-FIX behaviour was a SILENT WRONG EXTRACTION — ``plan.ok``
was ``True`` with zero blockers, and the helper that landed contained
statements (``debug_flag``, ``retries``) the plan never scored, while leaving
behind statements (``log.append("configured")``, ``log.append("scanning")``)
it DID score and promise. Strictly refuse-direction: the fingerprint check can
only turn a would-have-landed plan into a blocker, never the reverse.
"""

from __future__ import annotations

import ast

from app.execution.cross_file_rename import apply_rename
from app.execution.extract_method import (
    plan_extract,
    seam_fingerprint,
    suggest_extractions,
)


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# A function tall enough to be mined (>= _SUGGEST_FN_FLOOR lines), with one
# clean seam `suggest_extractions` reliably scores as its best window.
_VERSION_A = (
    "def process(items, config):\n"
    "    total = 0\n"
    "    count = 0\n"
    "    seen = set()\n"
    "    log = []\n"
    "    log.append('start')\n"
    "    log.append('configured')\n"
    "    log.append('scanning')\n"
    "    threshold = config.get('threshold', 0)\n"
    "    label = config.get('label', 'x')\n"
    "    mode = config.get('mode', 'sum')\n"
    "    verbose = config.get('verbose', False)\n"
    "    limit = config.get('limit', 1000)\n"
    "    offset = config.get('offset', 0)\n"
    "    running = 0\n"
    "    for item in items:\n"
    "        if item in seen:\n"
    "            continue\n"
    "        seen.add(item)\n"
    "        running += item\n"
    "        count += 1\n"
    "    total = running\n"
    "    if mode == 'sum':\n"
    "        result = total\n"
    "    else:\n"
    "        result = total / count if count else 0\n"
    "    if verbose:\n"
    "        log.append(f'result={result}')\n"
    "    log.append('done')\n"
    "    average = total / count if count else 0\n"
    "    return {\n"
    "        'total': total,\n"
    "        'count': count,\n"
    "        'result': result,\n"
    "        'average': average,\n"
    "        'label': label,\n"
    "        'threshold': threshold,\n"
    "        'limit': limit,\n"
    "        'offset': offset,\n"
    "        'log': log,\n"
    "    }\n"
)

# DRIFT: an earlier move in the same pass edits `process` first — two
# unrelated statements inserted right before the seam `suggest_extractions`
# scored on version A. `debug_flag` is read later in the function so a wrong
# splice is semantically observable, not merely cosmetic.
_VERSION_B = _VERSION_A.replace(
    "    total = 0\n    count = 0\n",
    "    total = 0\n"
    "    debug_flag = config.get('debug', False)\n"
    "    retries = 0\n"
    "    count = 0\n",
).replace(
    "    log.append('done')\n",
    "    if debug_flag:\n"
    "        log.append('debug-on')\n"
    "    log.append('done')\n",
)


def _seam(source):
    tree = ast.parse(source)
    seams = suggest_extractions(source, tree)
    assert seams, "fixture must yield a seam"
    return tree, seams[0]


# ══════════════════════════════════════════════════════════════════════════
# Frozen repro + negative controls at the plan_extract layer.
# ══════════════════════════════════════════════════════════════════════════


def test_stale_seam_is_refused_not_silently_extracted(tmp_path):
    """FROZEN REPRO: a plan-time seam (version A) applied against a drifted
    file (version B) must BLOCK, not silently splice the wrong statements."""
    _write(tmp_path, "m.py", _VERSION_A)
    tree_a, seam = _seam(_VERSION_A)
    fp = seam_fingerprint(tree_a, seam["start"], seam["end"])
    assert fp

    # The file drifts on disk between the seam scan and the actual apply.
    _write(tmp_path, "m.py", _VERSION_B)

    plan = plan_extract(str(tmp_path), "m.py", seam["start"], seam["end"],
                        seam["name"], expected_fingerprint=fp)
    assert not plan.ok
    assert any("stale seam" in b for b in plan.blockers), plan.blockers
    assert not plan.new_contents

    res = apply_rename(str(tmp_path), plan, verify=False)
    assert res["applied"] is False
    # Nothing landed: the file on disk is untouched (still version B).
    assert (tmp_path / "m.py").read_text(encoding="utf-8") == _VERSION_B


def test_unstale_seam_still_lands_with_fingerprint_supplied(tmp_path):
    """Negative control: an UNCHANGED file between plan and apply must still
    land cleanly when a fingerprint IS supplied — the guard never widens a
    refusal into the common, non-drifted case."""
    _write(tmp_path, "m.py", _VERSION_A)
    tree_a, seam = _seam(_VERSION_A)
    fp = seam_fingerprint(tree_a, seam["start"], seam["end"])

    plan = plan_extract(str(tmp_path), "m.py", seam["start"], seam["end"],
                        seam["name"], expected_fingerprint=fp)
    assert plan.ok, plan.blockers
    ast.parse(plan.new_contents["m.py"])

    res = apply_rename(str(tmp_path), plan, verify=False)
    assert res["applied"] is True


def test_no_fingerprint_supplied_is_byte_identical_to_before(tmp_path):
    """The parameter is OPT-IN: a caller that doesn't supply
    ``expected_fingerprint`` (the ``apex extract`` CLI's hand-typed line
    numbers, every pre-existing test) gets EXACTLY the pre-fix behaviour — the
    same drifted request without a fingerprint still extracts, because it has
    no plan-time snapshot to compare against in the first place."""
    _write(tmp_path, "m.py", _VERSION_A)
    seam = suggest_extractions(_VERSION_A)[0]
    _write(tmp_path, "m.py", _VERSION_B)

    plan = plan_extract(str(tmp_path), "m.py", seam["start"], seam["end"], seam["name"])
    assert plan.ok, plan.blockers
    assert plan.new_contents


# ══════════════════════════════════════════════════════════════════════════
# seam_fingerprint unit behaviour.
# ══════════════════════════════════════════════════════════════════════════


def test_seam_fingerprint_is_position_free():
    """A pure line-shift (same statements, different absolute lines) must
    fingerprint IDENTICALLY — ``ast.dump()`` omits lineno/col_offset."""
    src_a = "def f(a):\n    x = a + 1\n    y = x * 2\n    return y\n"
    src_b = "\n\n\n" + src_a  # every statement shifted down by 3 lines
    fp_a = seam_fingerprint(ast.parse(src_a), 2, 3)
    fp_b = seam_fingerprint(ast.parse(src_b), 5, 6)
    assert fp_a == fp_b


def test_seam_fingerprint_is_content_sensitive():
    """Different statements at the SAME lines must fingerprint differently."""
    src_a = "def f(a):\n    x = a + 1\n    y = x * 2\n    return y\n"
    src_b = "def f(a):\n    x = a - 1\n    y = x * 3\n    return y\n"
    fp_a = seam_fingerprint(ast.parse(src_a), 2, 3)
    fp_b = seam_fingerprint(ast.parse(src_b), 2, 3)
    assert fp_a != fp_b


def test_seam_fingerprint_is_statement_count_sensitive():
    """Dropping one statement from the run must change the fingerprint — the
    ``\\x1e`` join separator guards against a naive concatenation collision."""
    src = "def f(a):\n    x = a + 1\n    y = x * 2\n    z = y + 1\n    return z\n"
    fp_full = seam_fingerprint(ast.parse(src), 2, 4)
    fp_short = seam_fingerprint(ast.parse(src), 2, 3)
    assert fp_full != fp_short


def test_seam_fingerprint_none_when_range_does_not_resolve():
    # Lines 10-12 are outside the (3-line-bodied) function entirely.
    src = "def f(a):\n    x = a + 1\n    return x\n"
    assert seam_fingerprint(ast.parse(src), 10, 12) is None


# ══════════════════════════════════════════════════════════════════════════
# End-to-end through the real production wiring: _extract_moves.
# ══════════════════════════════════════════════════════════════════════════


def _campaign_project(tmp_path):
    (tmp_path / "app").mkdir()
    _write(tmp_path, "app/m.py", _VERSION_A)
    return tmp_path


def test_extract_moves_blocks_when_pass_drifts_the_file_first(tmp_path):
    """END-TO-END through the REAL ``_extract_moves`` wiring: build the move
    (as a campaign pass would, at the top of the pass), then simulate an
    earlier move in the SAME pass editing the file before this move's
    ``build_plan()`` finally runs."""
    from app.engine.objective_compiler import _extract_moves

    _campaign_project(tmp_path)
    moves = _extract_moves(str(tmp_path))
    assert moves and moves[0].operator == "extract"

    # An earlier move in the same pass edits app/m.py before this move applies.
    _write(tmp_path, "app/m.py", _VERSION_B)

    plan = moves[0].build_plan()
    assert not plan.ok
    assert any("stale seam" in b for b in plan.blockers), plan.blockers
    assert (tmp_path / "app" / "m.py").read_text(encoding="utf-8") == _VERSION_B


def test_extract_moves_still_lands_without_drift(tmp_path):
    """Negative control at the wiring level: no drift -> the move's plan
    still builds and lands exactly as it did before this fix."""
    from app.engine.objective_compiler import _extract_moves

    _campaign_project(tmp_path)
    moves = _extract_moves(str(tmp_path))
    assert moves

    plan = moves[0].build_plan()
    assert plan.ok, plan.blockers
    assert plan.new_contents
