"""Deep-mutation hardening for the SECURITY detectors in ``app.engine.detectors``.

The default mutation harness caps at 30 mutants in document order, so the
deeper security predicates — the ``hashlib.new("md5"|"sha1")`` weak-hash rule
and the ``subprocess shell=True`` *literal-command* discrimination — are never
seeded by a default run. Enumerating the FULL site universe with the mutation
tester surfaces survivors that the broad 3-file detector scope (test_detectors,
test_security_coverage_detectors_eyml, test_detectors_health_score_mutation_
hardening_eyml) is blind to.

These characterization tests pin the exact behaviours those survivors mutate, so
each REAL survivor below is killed regardless of which covering files run:

* ``_is_hashlib_new_weak_call`` (lines ~317-324): the ``owner == "hashlib"``
  AND ``attr == "new"`` guard, the ``node.args[0]`` first-arg index, the
  Constant+str shape check, the ``not in ("md5","sha1")`` digest membership, and
  the ``usedforsecurity=False`` exemption.
* ``_hashlib_new_weak_message`` (line ~328): the message names ``node.args[0]``.
* ``_shell_true_literal_command`` (line ~255): the ``or`` joining the
  whitespace-only guard and the metachar guard — a metachar-bearing or
  whitespace-only literal must fall THROUGH to the generic flag-only
  ``shell=True`` finding, never the ``subprocess-shell-literal`` finding.

The many ``return False -> return None`` survivors at the same sites are
EQUIVALENT mutants (every caller consumes these predicates as a truthiness
test, and ``None`` is falsy), so they are unkillable and intentionally not
targeted; they are documented in the module docstring of the deep-mutation
report rather than asserted here.

Deterministic, stdlib + pytest only. Style mirrors
``test_security_coverage_detectors_eyml``.
"""

from __future__ import annotations

from app.engine.detectors import (
    detect,
    has_hashlib_new_weak,
    has_subprocess_shell_literal,
    security_labels,
)


def _security_findings(src: str):
    return [i for i in detect(src) if i.category == "security"]


class TestHashlibNewWeakDetector:
    """``hashlib.new("md5"|"sha1")`` is the string-form sibling of the direct
    weak-hash finding; these pin the predicate's discriminating edges."""

    def test_fires_on_hashlib_new_md5(self) -> None:
        src = "import hashlib\nhashlib.new('md5')\n"
        findings = _security_findings(src)
        assert len(findings) == 1
        f = findings[0]
        assert f.fix_kind == "hashlib-new-weak"
        assert f.severity == "medium"
        assert f.line == 2
        assert has_hashlib_new_weak(src)
        assert "hashlib-new-weak" in security_labels(src)

    def test_fires_on_hashlib_new_sha1(self) -> None:
        src = "import hashlib\nhashlib.new('sha1')\n"
        assert has_hashlib_new_weak(src)

    def test_digest_name_is_case_insensitive(self) -> None:
        # Kills the ``first.value.lower() not in (...)`` membership: an
        # upper-case ``"SHA1"`` must still be recognised as weak.
        src = "import hashlib\nhashlib.new('SHA1')\n"
        assert has_hashlib_new_weak(src)

    def test_message_names_the_actual_digest(self) -> None:
        # Kills the ``node.args[0]`` index mutation in the message builder
        # (``args[0]`` -> ``args[1]`` would read the wrong / a missing arg) and
        # proves the literal flows into the message verbatim.
        src = "import hashlib\nhashlib.new('md5')\n"
        f = _security_findings(src)[0]
        assert 'hashlib.new("md5")' in f.message

    def test_strong_digest_sha256_does_not_fire(self) -> None:
        # Kills the membership flip (``not in`` -> ``in``) and the
        # ``return False`` -> ``return True`` constant flips: a strong digest
        # must NOT be flagged.
        src = "import hashlib\nhashlib.new('sha256')\n"
        assert not _security_findings(src)
        assert not has_hashlib_new_weak(src)
        assert "hashlib-new-weak" not in security_labels(src)

    def test_dynamic_digest_name_does_not_fire(self) -> None:
        # Kills the Constant/str shape guard (``and`` flip and the str check):
        # a non-constant first arg must be left alone (no false positive).
        src = "import hashlib\nhashlib.new(algo)\n"
        assert not has_hashlib_new_weak(src)

    def test_usedforsecurity_false_exempts(self) -> None:
        # Kills the ``not _has_usedforsecurity_false(node)`` return: an explicit
        # non-security declaration disables the finding.
        src = "import hashlib\nhashlib.new('md5', usedforsecurity=False)\n"
        assert not has_hashlib_new_weak(src)

    def test_non_hashlib_owner_does_not_fire(self) -> None:
        # Kills the ``owner == "hashlib"`` guard: a ``.new("md5")`` on some other
        # object must not be flagged.
        src = "registry.new('md5')\n"
        assert not has_hashlib_new_weak(src)

    def test_other_hashlib_attr_does_not_fire(self) -> None:
        # Kills the ``attr == "new"`` guard: ``hashlib.foo("md5")`` is not the
        # string-form constructor.
        src = "import hashlib\nhashlib.foo('md5')\n"
        assert not has_hashlib_new_weak(src)

    def test_hashlib_new_without_args_does_not_fire(self) -> None:
        # Kills the ``node.args`` truthiness guard / first-arg index: a bare
        # ``hashlib.new()`` has no digest name to inspect.
        src = "import hashlib\nhashlib.new()\n"
        assert not has_hashlib_new_weak(src)


class TestSubprocessShellLiteralDiscrimination:
    """``_shell_true_literal_command`` only returns the rewritable case; a
    whitespace-only or metachar-bearing literal must fall through to the generic
    flag-only ``shell=True`` finding (kills the ``or`` flip at line ~255)."""

    def test_safe_literal_command_fires_shell_literal(self) -> None:
        src = "import subprocess\nsubprocess.run('ls -la', shell=True)\n"
        findings = _security_findings(src)
        assert len(findings) == 1
        f = findings[0]
        assert f.fix_kind == "subprocess-shell-literal"
        assert f.severity == "high"
        assert has_subprocess_shell_literal(src)
        assert "subprocess-shell-literal" in security_labels(src)

    def test_metachar_literal_falls_through_to_generic(self) -> None:
        # A metachar-bearing command is NOT provably rewritable, so it must
        # produce the generic flag-only ``shell=True`` finding (empty fix_kind),
        # never ``subprocess-shell-literal``.
        src = "import subprocess\nsubprocess.run('ls; rm -rf x', shell=True)\n"
        findings = _security_findings(src)
        assert len(findings) == 1
        f = findings[0]
        assert f.fix_kind == ""
        assert "shell=True" in f.message
        assert not has_subprocess_shell_literal(src)
        assert "subprocess-shell-literal" not in security_labels(src)

    def test_whitespace_only_literal_falls_through_to_generic(self) -> None:
        # The other arm of the ``or`` guard: a whitespace-only command has no
        # token to rewrite, so it also falls through to the generic finding.
        src = "import subprocess\nsubprocess.run('   ', shell=True)\n"
        findings = _security_findings(src)
        assert len(findings) == 1
        assert findings[0].fix_kind == ""
        assert not has_subprocess_shell_literal(src)
        assert "subprocess-shell-literal" not in security_labels(src)
