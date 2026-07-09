"""java-finalize-field reflection/serialization soundness — the P1 UNSOUND-LANDING fix.

java-finalize-field seals a never-reassigned ``private`` field ``final`` on the proof
that "a private field cannot be written from outside its class, so the WHOLE
assignment surface is syntactic and lives in this one file's parse tree". That proof
has ONE hole: a writer that sets a field WITHOUT a ``=``.

* ``java.lang.reflect.Field`` — ``f.setAccessible(true); f.setInt(this, 99)`` — writes
  a private field reflectively, bypassing the ``=`` surface the driver scans.
* A ``Serializable`` class's private fields are set REFLECTIVELY by the deserializer
  (``ObjectInputStream``/``defaultReadObject``), again with no ``=``.

Sealing such a field ``final`` makes the reflective write throw
``IllegalAccessException`` / no-op at RUNTIME — a real breakage. The Tier-A re-parse
oracle CANNOT catch it: ``final`` is not in the ``{types}+{fields}+{methods}``
fact-set, so the spliced file re-parses fact-identical and would wrongly PASS.

The fix is the cheapest sound option: the driver REFUSES the WHOLE compilation unit
(emits no final-targets) when the unit references ``java.lang.reflect`` (an import or
a ``Field``-setter member select) OR any class ``implements Serializable`` — a
single-file parser cannot prove WHICH private field such a writer leaves alone, so it
finalises nothing. This mirrors the existing multi-declarator and false-``final``
(nested-inner-class reassignment, ``java_false_final``) refusals.

This module proves: (1) both new corpus fixtures (``java_reflective_field`` /
``java_serializable_field``) are REFUSED through the driver AND the plan path; (2) a
NORMAL never-reassigned private field — no reflection, no Serializable — is STILL
offered (no over-refusal); (3) the fully-qualified-without-import and
``java.io.Serializable`` shapes are caught too; (4) the heavy soundness corpus sweep
marks both shapes ``refused`` for java-finalize-field. The heavy ``java`` tests skip
cleanly when no JDK is on PATH; the pure refusal/corpus-presence checks always run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.java.java_tool import final_targets
from app.execution.objectives.java_finalize_field import (
    finalizable_targets,
    plan_java_finalize_field,
)

# The two new corpus shapes, as ``(shape_dir, rel_to_pkg_source)`` under the corpus.
_REFLECTIVE = ("java_reflective_field", "pkg/Reflective.java")
_SERIALIZABLE = ("java_serializable_field", "pkg/Account.java")

# A NORMAL never-reassigned private field (no reflection, no Serializable): the
# over-refusal control — this MUST still be offered a ``final``.
_PLAIN_JAVA = (
    "package pkg;\n"
    "\n"
    "public class Plain {\n"
    "    private int secret = 0;\n"
    "\n"
    "    int read() {\n"
    "        return secret;\n"
    "    }\n"
    "}\n"
)


def _jdk_ok() -> bool:
    """True when a ``java`` launcher is on PATH — the minimum for the LLM-free driver
    (``final-targets``) to run."""
    return shutil.which("java") is not None


_needs_jdk = pytest.mark.skipif(not _jdk_ok(), reason="no JDK (java) on PATH")


def _corpus_root() -> Path:
    from app.engine.soundness_audit import corpus_root, repo_root

    return corpus_root(repo_root())


def _with_pom(root: Path) -> Path:
    (root / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion></project>\n", encoding="utf-8")
    return root


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


# --- the new corpus fixtures exist and carry the marker (always runs) ----------

def test_new_corpus_fixtures_present_with_marker():
    # Mirrors java_false_final: a build.gradle marker at the shape root + a pkg/ source.
    root = _corpus_root()
    for shape, rel in (_REFLECTIVE, _SERIALIZABLE):
        assert (root / shape / "build.gradle").is_file(), f"{shape} missing marker"
        assert (root / shape / rel).is_file(), f"{shape} missing {rel}"


# --- driver path: both traps are REFUSED (need java) ---------------------------

@_needs_jdk
def test_driver_refuses_reflective_field_fixture():
    root = _corpus_root() / _REFLECTIVE[0]
    # `secret` is reflectively written via Field.setInt — NEVER syntactically assigned,
    # so a naive scan would offer it. The unit imports java.lang.reflect.Field, so the
    # driver refuses the WHOLE unit.
    assert final_targets(root, _REFLECTIVE[1]) == []


@_needs_jdk
def test_driver_refuses_serializable_field_fixture():
    root = _corpus_root() / _SERIALIZABLE[0]
    # `id` is set by the deserializer reflectively; the class implements Serializable,
    # so the driver refuses the whole unit.
    assert final_targets(root, _SERIALIZABLE[1]) == []


@_needs_jdk
def test_plan_lands_nothing_on_reflective_fixture():
    # The end-to-end plan path: finalizable_targets empty -> plan is an honest no-op,
    # nothing landed (never-fake-green).
    root = _corpus_root() / _REFLECTIVE[0]
    assert finalizable_targets(root, _REFLECTIVE[1]) == []
    plan = plan_java_finalize_field(str(root), _REFLECTIVE[1])
    assert not plan.new_contents
    assert not plan.blockers


@_needs_jdk
def test_plan_lands_nothing_on_serializable_fixture():
    root = _corpus_root() / _SERIALIZABLE[0]
    assert finalizable_targets(root, _SERIALIZABLE[1]) == []
    plan = plan_java_finalize_field(str(root), _SERIALIZABLE[1])
    assert not plan.new_contents
    assert not plan.blockers


# --- NO over-refusal: a normal never-reassigned private field STILL gets `final` ---

@_needs_jdk
def test_normal_field_still_offered_no_over_refusal(tmp_path: Path):
    # The refusal is SCOPED to reflection/Serializable: a plain never-reassigned
    # private field (no import, no setter, no Serializable) is STILL offered a final.
    root = _project(tmp_path, "pkg/Plain.java", _PLAIN_JAVA)
    names = [t.name for t in final_targets(root, "pkg/Plain.java")]
    assert names == ["secret"]


@_needs_jdk
def test_normal_field_plan_still_lands(tmp_path: Path):
    # And the plan over a marked project STILL seals it (the objective keeps working
    # for the ordinary case the fix must not disturb).
    root = _with_pom(tmp_path)
    _project(root, "pkg/Plain.java", _PLAIN_JAVA)
    plan = plan_java_finalize_field(str(root), "pkg/Plain.java")
    assert plan.ok
    assert "private final int secret = 0;" in plan.new_contents["pkg/Plain.java"]


# --- edge shapes: fully-qualified reflection (no import) + java.io.Serializable ---

@_needs_jdk
def test_driver_refuses_fully_qualified_reflect_without_import(tmp_path: Path):
    # A reflective write with NO import (fully-qualified java.lang.reflect.Field) is
    # caught by the setAccessible/setInt member-select scan, not just the import gate.
    src = (
        "package pkg;\n"
        "public class R {\n"
        "    private int secret = 0;\n"
        "    void poke() throws Exception {\n"
        "        java.lang.reflect.Field f = R.class.getDeclaredField(\"secret\");\n"
        "        f.setAccessible(true);\n"
        "        f.setInt(this, 99);\n"
        "    }\n"
        "    int read() { return secret; }\n"
        "}\n"
    )
    root = _project(tmp_path, "pkg/R.java", src)
    assert final_targets(root, "pkg/R.java") == []


@_needs_jdk
def test_driver_refuses_qualified_java_io_serializable(tmp_path: Path):
    # `implements java.io.Serializable` (the qualified form) is caught via the trailing
    # simple name, exactly like the bare `implements Serializable`.
    src = (
        "package pkg;\n"
        "public class Q implements java.io.Serializable {\n"
        "    private int id = 0;\n"
        "    int read() { return id; }\n"
        "}\n"
    )
    root = _project(tmp_path, "pkg/Q.java", src)
    assert final_targets(root, "pkg/Q.java") == []


@_needs_jdk
def test_driver_refuses_import_only_no_setter(tmp_path: Path):
    # The import-presence gate alone refuses: even without a visible setter call, a
    # unit that imports java.lang.reflect.Field is presumed to write a field
    # reflectively (the simplest conservative gate).
    src = (
        "package pkg;\n"
        "import java.lang.reflect.Field;\n"
        "public class I {\n"
        "    private int secret = 0;\n"
        "    Field handle() throws Exception {\n"
        "        return I.class.getDeclaredField(\"secret\");\n"
        "    }\n"
        "    int read() { return secret; }\n"
        "}\n"
    )
    root = _project(tmp_path, "pkg/I.java", src)
    assert final_targets(root, "pkg/I.java") == []


@_needs_jdk
def test_driver_refuses_reflect_wildcard_import(tmp_path: Path):
    # A wildcard `import java.lang.reflect.*;` is caught by the same import gate.
    src = (
        "package pkg;\n"
        "import java.lang.reflect.*;\n"
        "public class W {\n"
        "    private int secret = 0;\n"
        "    void poke() throws Exception {\n"
        "        Field f = W.class.getDeclaredField(\"secret\");\n"
        "        f.setInt(this, 7);\n"
        "    }\n"
        "    int read() { return secret; }\n"
        "}\n"
    )
    root = _project(tmp_path, "pkg/W.java", src)
    assert final_targets(root, "pkg/W.java") == []


# --- the heavy soundness corpus marks both shapes refused for java-finalize-field ---

@_needs_jdk
@pytest.mark.timeout(600)  # heavy JVM corpus sweep: 120s global fits fast
# tests, not a javac/JVM cold-start under -j4 gate CPU contention (no assertion changed)
def test_soundness_corpus_refuses_both_new_java_shapes():
    # The standing corpus sweep (heavy path: java-finalize-field is expensive) must
    # mark both reflection/serialization shapes `refused` — the in-repo proof, exactly
    # as test_refuses_on_java_false_final_corpus_shape asserts for java_false_final.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    # ``only`` slices the heavy sweep to THIS objective's row (byte-identical to its row
    # in the full sweep — per-objective independent), so the test pays just this
    # objective's JVM cost, not the whole ~2-minute sweep, staying under the per-test
    # timeout under a parallel-chunked gate.
    corpus = corpus_refusal_findings(repo_root(), include_heavy=True,
                                     only={"java-finalize-field"})
    cells = corpus.get("java-finalize-field", {})
    assert cells, "java-finalize-field should be swept in the heavy corpus path"
    assert cells.get("java_reflective_field") == "refused"
    assert cells.get("java_serializable_field") == "refused"
    # and it stays a clean refusal on EVERY corpus shape (no shape regresses).
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"
