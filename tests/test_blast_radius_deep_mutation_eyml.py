"""Deep-mutation hardening for ``app.engine.blast_radius``.

The default mutation run caps at 30 seeded faults (document order), so the back
half of the module — ``changed_from_git``'s ``subprocess.run`` keyword wiring and
the empty-input contract of ``_common_prefix`` — never gets a mutant. This file
characterizes those behaviors directly so the masked survivors are killed:

  * ``_common_prefix([])`` returns the empty STRING ``""`` (not ``None``): the
    ``return ""`` early-out (the empty-packages contract).
  * ``changed_from_git`` passes ``capture_output=True`` and ``text=True`` to
    ``subprocess.run`` so it reads textual stdout; flipping either to ``False``
    (stdout becomes ``None`` / ``bytes``) must change the observed result.
  * ``changed_from_git`` returns ``[]`` (not ``None``) when ``subprocess.run``
    raises ``OSError``/``ValueError`` — the conservative failure contract.

Several adjacent back-half mutants are provably EQUIVALENT (no test can kill
them) and are documented at the bottom rather than asserted.

Deterministic and hermetic: the git helper is exercised with an in-process fake
``subprocess.run`` that HONORS the ``capture_output``/``text`` keywords (the
existing suite's fake ignores them, which is exactly why these mutants survive).
No network, no real git, no tmp_path needed. Style mirrors
tests/test_blast_radius_branch_gaps.py.
"""

from __future__ import annotations

from app.engine import blast_radius as br
from app.engine.blast_radius import _common_prefix, changed_from_git


def _kwarg_honoring_run(stdout_text: str, returncode: int = 0):
    """A fake ``subprocess.run`` that mimics the real one's kwarg semantics.

    Unlike the suite's existing fakes (which return a fixed ``stdout`` whatever
    the kwargs), this honors the two keywords ``changed_from_git`` relies on:

      * ``capture_output=False`` -> ``stdout`` is ``None`` (real behavior), so a
        downstream ``.splitlines()`` would blow up;
      * ``text=False`` -> ``stdout`` is ``bytes`` rather than ``str``, so the
        ``.endswith(".py")`` filter matches nothing.

    This makes the ``capture_output``/``text`` keywords observable, which is what
    lets the off-by-default 30-cap survivors at those sites be killed.
    """

    def _run(cmd, cwd=None, capture_output=False, text=False, check=False, **_):
        class _Proc:
            pass

        proc = _Proc()
        proc.returncode = returncode
        if not capture_output:
            proc.stdout = None
        elif text:
            proc.stdout = stdout_text
        else:
            proc.stdout = stdout_text.encode("utf-8")
        return proc

    return _run


def test_common_prefix_of_empty_is_empty_string_not_none():
    # The ``return ""`` early-out: with no packages there is no shared prefix, and
    # the contract is the empty STRING (callers join/concatenate it as text and
    # test it with ``if not prefix``). The ``return ""`` -> ``return None`` mutant
    # would change the return type; pin the exact value and type here.
    result = _common_prefix([])
    assert result == ""
    assert isinstance(result, str)


def test_changed_from_git_reads_textual_captured_stdout(monkeypatch):
    # ``changed_from_git`` must call ``subprocess.run`` with BOTH
    # ``capture_output=True`` and ``text=True`` so it gets a real text stdout to
    # parse. Flip either to False and the result changes:
    #   * capture_output=False -> stdout is None -> .splitlines() raises;
    #   * text=False           -> stdout is bytes -> nothing ends with ".py".
    # The kwarg-honoring fake exposes both, so this single assertion kills the
    # ``True`` -> ``False`` mutant on each keyword.
    monkeypatch.setattr(
        br.subprocess, "run", _kwarg_honoring_run("app/a.py\napp/b.py\n")
    )
    out = changed_from_git("/some/root")
    assert out == ["app/a.py", "app/b.py"]


def test_changed_from_git_text_flag_is_required_for_py_filter(monkeypatch):
    # A second, sharper witness for ``text=True``: a single ``.py`` line. With
    # text mode the file is reported; with ``text=False`` stdout would be bytes
    # and ``rel.endswith(".py")`` (str compare) matches nothing -> ``[]``.
    monkeypatch.setattr(
        br.subprocess, "run", _kwarg_honoring_run("pkg/only.py\n")
    )
    assert changed_from_git("/some/root") == ["pkg/only.py"]


def test_changed_from_git_oserror_returns_empty_list_not_none(monkeypatch):
    # The conservative failure contract: ANY ``OSError``/``ValueError`` from
    # ``subprocess.run`` yields ``[]`` (a list), never ``None`` and never a
    # raise. Kills the ``return []`` -> ``return None`` mutant on that arm.
    def _boom(*_a, **_k):
        raise OSError("git not found")

    monkeypatch.setattr(br.subprocess, "run", _boom)
    result = changed_from_git("/some/root")
    assert result == []
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# EQUIVALENT mutants in the off-by-default tail (documented, not asserted):
#
#   * L208 ``round(matching / n, 4)`` -> ``round(..., 5)`` and
#     L209 ``score >= _TIGHT_THRESHOLD`` -> ``score > _TIGHT_THRESHOLD``:
#     these live in ``_prefix_cohesion`` *after* the ``if not prefix`` early
#     return. ``_common_prefix`` returns a prefix shared by EVERY package, so
#     every package either equals it or starts with ``prefix + "/"`` -> matching
#     == n -> score is always exactly ``1.0`` (or the function returned ``0.0``
#     earlier). A fractional score is unreachable, so rounding precision 4-vs-5
#     and the ``>=``/``>`` boundary at 0.5 are both unobservable. EQUIVALENT.
#
#   * L122 ``first = parts[0]`` -> ``first = parts[1]`` in ``_common_prefix``:
#     a component is only appended when ``all(part == first for part in parts)``;
#     for that to hold, every component (including ``parts[0]`` and ``parts[1]``)
#     is identical, so substituting ``parts[1]`` for ``parts[0]`` cannot change
#     which components are appended or where the loop breaks. EQUIVALENT.
#
#   * L242 ``pkg = packages[0]`` -> ``pkg = packages[1]`` in ``_compute_cohesion``:
#     reached only under ``len(set(packages)) == 1`` (all packages identical), so
#     ``packages[0]`` and ``packages[1]`` are the same value and the reason string
#     is byte-identical. EQUIVALENT.
# ---------------------------------------------------------------------------
