"""harden develop objective — the ALREADY-BUILT 14-patcher security engine
(:mod:`app.execution.semantic.transforms.security`) wired onto the autonomous
develop surface so it LANDS real security fixes, per finding.

This adds NO new detector and NO new safety machinery: findings come from the
existing :func:`app.engine.detectors.security_labels` scan and each fix is the
existing ``security.apply`` output, routed through the SAME verified-with-rollback
engine every develop move uses. The objective is multi-finding-per-module — a file
with several security labels yields one move per label.

Covers: registration as a self-registered spec; the ``(module, label)`` landability
gate (one move per finding, fixture/non-library refusal applied FIRST); a Tier-1
rewrite landed verified AND rolled-back-on-red (os.system → subprocess.run +
shlex.split, +import subprocess); each other Tier-1 rung (eval / yaml / bare-except /
base-exception / hashlib-new); a Tier-0 annotation (pickle → reviewable ``# SECURITY``
comment, re-parses, else byte-identical); the engine's safety declines (non-literal
eval, dynamic shell=True) surfacing as no-ops; the fixture/non-library refusal;
fitness reaching 0 after the fix lands; idempotency (no double ``# SECURITY``); the
FIVE-registry 1:1 parity (manifest / soundness-strategy / operator-value / facet /
synonym); the COUNT pins (77 / 35); the synonym redirect
(``resolve_objective("harden") == "harden"``, fortify / secure / lock-down → harden,
sanitize stays on modernize); and the soundness-corpus refusal (harden refuses on
every standing fixture — none carries a security finding).

The pure-AST / static tests run on the fast gate; the two verified-apply tests spawn
a tiny one-module/one-test pytest subprocess (the same shape every objective's
end-to-end test uses) so the "lands working code, verified, auto-rolled-back" claim
is proven against the REAL engine, not asserted.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.harden import (
    _content_plan,
    _landable,
    fitness,
    moves,
)

_PHRASE = "the security vulnerability to harden"


# --- project scaffolds -------------------------------------------------------

def _suite_project(tmp_path: Path) -> Path:
    """A minimal importable project tree apply_rename can run a suite against."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _own_project(tmp_path: Path, rel: str, src: str) -> Path:
    """A tree with one own (non-fixture) module carrying ``src``."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


# --- registration ------------------------------------------------------------

def test_objective_is_registered():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs().get("harden")
    assert spec is not None
    assert spec.name == "harden"
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_not_expensive_and_not_scope_verify():
    # The security scan is a cheap in-process AST pass, so harden stays on the fast
    # board (NOT expensive) and full-suite-gated (NOT scope_verify → A3-clean).
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["harden"]
    assert getattr(spec, "expensive", False) is False
    assert getattr(spec, "scope_verify", False) is False


def test_objective_resolves_through_compiler_map():
    from app.engine.objective_compiler import available_objectives

    assert "harden" in available_objectives()


# --- landability: one move per finding, multi-finding per module -------------

def test_landable_yields_one_pair_per_security_label(tmp_path: Path):
    src = (
        "import os\n"
        "import pickle\n"
        "\n"
        "def run(cmd):\n"
        "    os.system(cmd)\n"
        "\n"
        "def load(b):\n"
        "    return pickle.loads(b)\n"
    )
    _own_project(tmp_path, "app/vuln.py", src)
    pairs = _landable(str(tmp_path))
    assert ("app/vuln.py", "os.system") in pairs   # Tier-1 rung
    assert ("app/vuln.py", "pickle") in pairs       # Tier-0 rung
    # Exactly one entry per (module, label) — the multi-finding granularity.
    assert len(pairs) == len(set(pairs))


def test_moves_one_per_landable_pair_with_harden_operator(tmp_path: Path):
    src = (
        "import os\n"
        "import pickle\n"
        "\n"
        "def run(cmd):\n"
        "    os.system(cmd)\n"
        "\n"
        "def load(b):\n"
        "    return pickle.loads(b)\n"
    )
    _own_project(tmp_path, "app/vuln.py", src)
    mvs = moves(str(tmp_path))
    assert len(mvs) == 2
    for m in mvs:
        assert m.operator == "harden"
        assert m.target.startswith("app/vuln.py:harden-")
        assert "security finding in app/vuln.py" in m.description
        # The build_plan thunk re-derives a real, rollback-ready plan.
        plan = m.build_plan()
        assert plan.new_contents["app/vuln.py"]
        assert plan.originals["app/vuln.py"] == src  # original captured for rollback


def test_fitness_counts_landable_findings(tmp_path: Path):
    src = "import pickle\n\ndef load(b):\n    return pickle.loads(b)\n"
    _own_project(tmp_path, "app/vuln.py", src)
    assert fitness(str(tmp_path)) == 1.0


def test_no_findings_is_zero_fitness_and_no_moves(tmp_path: Path):
    _own_project(tmp_path, "app/clean.py", "def add(a, b):\n    return a + b\n")
    assert fitness(str(tmp_path)) == 0.0
    assert moves(str(tmp_path)) == []


# --- Tier-1 rewrite landed VERIFIED, and rolled back on RED ------------------

def test_tier1_os_system_rewrite_lands_verified(tmp_path: Path):
    # os.system(cmd) -> subprocess.run(shlex.split(cmd), check=True) + the imports.
    # The suite runs a SUCCEEDING command, so check=True does not raise -> green ->
    # the rewrite STAYS landed (a genuine verified security fix).
    _suite_project(tmp_path)
    (tmp_path / "app" / "shell.py").write_text(
        "import os\n\ndef run(cmd):\n    os.system(cmd)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_shell.py").write_text(
        "from app.shell import run\n"
        "def test_run_ok():\n"
        "    run('true')\n",  # exit 0 -> check=True is a no-op
        encoding="utf-8")

    plan = _content_plan(str(tmp_path), "app/shell.py", "os.system")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "shell.py").read_text(encoding="utf-8")
    ast.parse(landed)  # never lands broken Python
    assert "subprocess.run(shlex.split(cmd), check=True)" in landed
    assert "import subprocess" in landed
    assert "import shlex" in landed


def test_tier1_rewrite_rolls_back_on_red(tmp_path: Path):
    # The never-fake-green capstone. os.system SWALLOWS a non-zero exit (returns the
    # code); subprocess.run(check=True) RAISES CalledProcessError. A suite that
    # relied on the silent behaviour goes RED -> the rewrite is rolled back
    # byte-for-byte, never left landed.
    _suite_project(tmp_path)
    orig = "import os\n\ndef run(cmd):\n    os.system(cmd)\n"
    (tmp_path / "app" / "shell.py").write_text(orig, encoding="utf-8")
    (tmp_path / "tests" / "test_shell.py").write_text(
        "from app.shell import run\n"
        "def test_nonzero_is_silent():\n"
        "    run('false')\n",  # exit 1: silent under os.system, raises after rewrite
        encoding="utf-8")

    plan = _content_plan(str(tmp_path), "app/shell.py", "os.system")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    assert (tmp_path / "app" / "shell.py").read_text(encoding="utf-8") == orig


# --- each other Tier-1 rung lands a real rewrite (pure, no subprocess) -------

def _landed_content(tmp_path: Path, rel: str, src: str, label: str) -> str:
    _own_project(tmp_path, rel, src)
    plan = _content_plan(str(tmp_path), rel, label)
    out = plan.new_contents[rel]
    ast.parse(out)  # every rung lands parseable Python
    return out


def test_tier1_eval_to_literal_eval(tmp_path: Path):
    out = _landed_content(
        tmp_path, "app/m.py", "def f(data):\n    return eval(data)\n", "eval")
    assert "ast.literal_eval(data)" in out
    assert "import ast" in out


def test_tier1_yaml_load_to_safe_load(tmp_path: Path):
    out = _landed_content(
        tmp_path, "app/m.py", "import yaml\n\ndef f(s):\n    return yaml.load(s)\n",
        "yaml")
    assert "yaml.safe_load(s)" in out


def test_tier1_bare_except_to_exception(tmp_path: Path):
    # A RE-RAISING bare except is the safe-to-narrow case (Tier-1 rewrite).
    out = _landed_content(
        tmp_path, "app/m.py",
        "def f():\n    try:\n        g()\n    except:\n        raise\n",
        "bare except")
    assert "except Exception:" in out


def test_tier1_base_exception_to_exception(tmp_path: Path):
    out = _landed_content(
        tmp_path, "app/m.py",
        "def f():\n    try:\n        g()\n    except BaseException:\n        h()\n",
        "base-exception")
    assert "except Exception:" in out
    assert "BaseException" not in out


def test_tier1_hashlib_new_weak_usedforsecurity_false(tmp_path: Path):
    out = _landed_content(
        tmp_path, "app/m.py",
        'import hashlib\n\ndef f():\n    return hashlib.new("md5")\n',
        "hashlib-new-weak")
    assert "usedforsecurity=False" in out


# --- Tier-0 annotation: behaviour-identical # SECURITY comment ---------------

def test_tier0_pickle_annotation_is_behavior_identical(tmp_path: Path):
    src = "import pickle\n\ndef load(b):\n    return pickle.loads(b)\n"
    out = _landed_content(tmp_path, "app/m.py", src, "pickle")
    assert "# SECURITY (" in out
    assert "pickle.loads" in out  # the call itself is UNCHANGED (annotation only)
    # Byte-identical apart from the single inserted comment line.
    without_comment = "".join(
        ln for ln in out.splitlines(keepends=True) if "# SECURITY" not in ln)
    assert without_comment == src


# --- the engine's safety declines surface as honest no-ops -------------------

def test_refuses_non_literal_eval(tmp_path: Path):
    # eval('a * b') is a RUNTIME expression, not a Python literal — narrowing it to
    # ast.literal_eval would ship code that crashes, so the engine declines and the
    # pair is NOT landable.
    _own_project(tmp_path, "app/m.py", "def f(a, b):\n    return eval('a * b')\n")
    assert _landable(str(tmp_path)) == []
    assert moves(str(tmp_path)) == []


def test_refuses_dynamic_shell_true(tmp_path: Path):
    # subprocess.run(c, shell=True) with a NON-literal command has no
    # behaviour-preserving shell-free form, so the engine declines (it would be a
    # Tier-0 flag at most — never a silent rewrite here).
    src = "import subprocess\n\ndef f(c):\n    subprocess.run(c, shell=True)\n"
    _own_project(tmp_path, "app/m.py", src)
    plan = _content_plan(str(tmp_path), "app/m.py", "subprocess-shell-literal")
    assert not plan.new_contents  # declined → empty plan → not landable


# --- fixture / non-library refusal (applied FIRST) ---------------------------

def test_refuses_fixture_and_non_library_files(tmp_path: Path):
    # A real vuln in a test/fixture file AND in a packaging script (conftest.py /
    # setup.py) must NOT be surfaced — fixing those is fixture/config noise, not a
    # library contribution. The gate is applied before the per-label scan.
    vuln = "import pickle\n\ndef f(b):\n    return pickle.loads(b)\n"
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(vuln, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(vuln, encoding="utf-8")
    (tmp_path / "setup.py").write_text(vuln, encoding="utf-8")
    assert _landable(str(tmp_path)) == []


# --- fitness reaches 0 after the fix lands -----------------------------------

def test_fitness_reaches_zero_after_applying(tmp_path: Path):
    # Apply the (only) landable fix in-place; the rescan finds nothing left.
    src = "import pickle\n\ndef load(b):\n    return pickle.loads(b)\n"
    _own_project(tmp_path, "app/m.py", src)
    assert fitness(str(tmp_path)) == 1.0
    plan = _content_plan(str(tmp_path), "app/m.py", "pickle")
    (tmp_path / "app" / "m.py").write_text(
        plan.new_contents["app/m.py"], encoding="utf-8")
    assert fitness(str(tmp_path)) == 0.0


# --- idempotency: no double # SECURITY ---------------------------------------

def test_idempotent_no_double_security_comment(tmp_path: Path):
    src = "import pickle\n\ndef load(b):\n    return pickle.loads(b)\n"
    _own_project(tmp_path, "app/m.py", src)
    once = _content_plan(str(tmp_path), "app/m.py", "pickle").new_contents["app/m.py"]
    assert once.count("# SECURITY") == 1
    # Re-scan against the already-annotated source: the site is already flagged, so
    # the second pass is an honest no-op (no second comment, nothing landable).
    (tmp_path / "app" / "m.py").write_text(once, encoding="utf-8")
    assert _content_plan(str(tmp_path), "app/m.py", "pickle").new_contents == {}
    assert ("app/m.py", "pickle") not in _landable(str(tmp_path))


# --- the FIVE-registry 1:1 parity --------------------------------------------

def test_manifest_classifies_harden_as_concrete():
    from app.engine.north_star_audit import OBJECTIVE_MANIFEST, classify_objectives
    from app.engine.objective_compiler import available_objectives

    assert "harden" in OBJECTIVE_MANIFEST["CONCRETE"]
    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "harden" in buckets["CONCRETE"]


def test_soundness_strategy_declared_and_not_scope_verify():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert SOUNDNESS_STRATEGY["harden"] == (
        "suite-catches-runtime+security-rewrite(tier1)"
        "+behavior-identical-annotation(tier0)+engine-decline-on-unsafe")
    assert "harden" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_operator_value_present_and_bridges_from_name():
    from app.engine.move_value import OPERATOR_VALUE, move_value, objective_value

    assert OPERATOR_VALUE["harden"] == 0.65
    # moves() emits operator="harden"; the name->operator bridge agrees.
    assert objective_value("harden") == move_value("harden") == 0.65


def test_facet_phrase_routes_to_harden():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(f"...{_PHRASE}...") == "harden"


def test_synonym_redirect_repoints_security_verbs_to_harden():
    from app.engine.objective_compiler import resolve_objective

    # Exact name wins first.
    assert resolve_objective("harden") == "harden"
    # The security-intent verbs now route to the security lens, not modernize.
    assert resolve_objective("please fortify this module") == "harden"
    assert resolve_objective("secure the request path") == "harden"
    assert resolve_objective("lock down the parser") == "harden"
    # sanitize/sanitise deliberately STAY on modernize (input-cleanup is tidy).
    assert resolve_objective("sanitize the input") == "modernize"
    assert resolve_objective("sanitise the input") == "modernize"


def test_harden_synonym_repointed_from_modernize_to_harden():
    # The old ``("harden", "modernize")`` row was MISLEADING (a phrase merely
    # CONTAINING "harden" used to route to modernize); it is repointed to the
    # dedicated harden lens, and no harden→modernize row survives.
    from app.engine.objective_compiler import _OBJECTIVE_SYNONYMS

    assert ("harden", "harden") in _OBJECTIVE_SYNONYMS
    assert ("harden", "modernize") not in _OBJECTIVE_SYNONYMS
    # A phrase that merely contains the verb (no exact name) still routes to harden.
    from app.engine.objective_compiler import resolve_objective

    assert resolve_objective("harden the auth path") == "harden"


# --- the count pins ----------------------------------------------------------

def test_counts_are_thirty_six_concrete_of_seventy_eight():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 90  # 89 after js-strengthen-tests (89th, CONCRETE) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 45  # js-strengthen-tests (89th) is CONCRETE


# --- both audits still PASS --------------------------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


# --- soundness corpus: harden refuses on every standing fixture --------------

def test_refuses_on_python_soundness_corpus():
    # harden is NOT expensive (pure-AST scan), so it is swept on the DEFAULT cheap
    # path. The standing corpus carries no security finding, so the objective
    # REFUSES (empty plan) on every shape — never a landed change.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=False)
    cells = corpus.get("harden", {})
    assert cells, "harden should be swept on the cheap corpus path"
    for shape, verdict in cells.items():
        assert verdict == "refused", f"{shape}: {verdict}"


# --- conservative on UNTESTED code: never land broken / behaviour-changing ----
# These pin the adversarial-audit fixes (the suite-gate only catches TESTED
# modules; harden must be sound even on untested files it touches).

def test_never_lands_syntax_error_on_pickle_continuation(tmp_path: Path):
    # The flag would split a backslash line-continuation and produce a SyntaxError;
    # the patcher refuses the site, so harden surfaces NO landable move (and could
    # never land non-parsing Python even if it did — see the floor test below).
    src = "import pickle\nval = \\\n    pickle.loads(raw)\n"
    _own_project(tmp_path, "app/m.py", src)
    assert _content_plan(str(tmp_path), "app/m.py", "pickle").new_contents == {}
    assert ("app/m.py", "pickle") not in _landable(str(tmp_path))


def test_content_plan_floor_refuses_non_parsing_python(tmp_path: Path, monkeypatch):
    # The never-fake-green floor in objective_compiler._content_plan: even if a
    # patcher (hypothetically) emitted non-parsing Python, the .py reparse guard
    # drops it rather than recording it — harden can NEVER land a SyntaxError.
    from app.execution.semantic.result import SemanticPatchResult

    def _broken(rel, source, title):
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel,
                "new_content": "def broken(:\n    pass\n",  # SyntaxError
                "expected_old_content": source,
            }],
            transform_type="x", rationale=["x"])

    monkeypatch.setattr(
        "app.execution.semantic.transforms.security.apply", _broken)
    _own_project(tmp_path, "app/m.py", "x = 1\n")
    assert _content_plan(str(tmp_path), "app/m.py", "anything").new_contents == {}


def test_content_plan_floor_records_parsing_python(tmp_path: Path, monkeypatch):
    # The floor is not over-eager: a VALID rewrite is still recorded.
    from app.execution.semantic.result import SemanticPatchResult

    def _ok(rel, source, title):
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel,
                "new_content": "x = 2\n",
                "expected_old_content": source,
            }],
            transform_type="x", rationale=["x"])

    monkeypatch.setattr(
        "app.execution.semantic.transforms.security.apply", _ok)
    _own_project(tmp_path, "app/m.py", "x = 1\n")
    assert _content_plan(str(tmp_path), "app/m.py", "anything").new_contents == {
        "app/m.py": "x = 2\n"}


def test_swallowing_bare_except_lands_annotation_not_narrowing(tmp_path: Path):
    # A SWALLOWING bare except is annotated (behaviour-preserving), not narrowed to
    # Exception (which could stop catching SystemExit/KeyboardInterrupt).
    out = _landed_content(
        tmp_path, "app/m.py",
        "def f():\n    try:\n        g()\n    except:\n        pass\n",
        "bare except")
    assert "except Exception:" not in out
    assert "# SECURITY (Apex: bare except" in out


def test_os_system_used_result_lands_annotation_not_rewrite(tmp_path: Path):
    # os.system whose int result is USED is annotated, not rewritten to
    # subprocess.run(check=True) (which would change result/exit-code semantics).
    out = _landed_content(
        tmp_path, "app/m.py",
        "import os\ndef f(cmd):\n    rc = os.system(cmd)\n    return rc\n",
        "os.system")
    assert "shlex.split" not in out  # NOT rewritten
    assert "import subprocess" not in out
    assert "rc = os.system(cmd)" in out  # call unchanged
    assert "# SECURITY (Apex: os.system" in out


def test_os_system_metachar_literal_lands_annotation(tmp_path: Path):
    out = _landed_content(
        tmp_path, "app/m.py",
        'import os\nos.system("a && b")\n',
        "os.system")
    assert "shlex.split" not in out
    assert "# SECURITY (Apex: os.system" in out


def test_os_system_double_quoted_discarded_still_rewrites_cleanly(tmp_path: Path):
    # The safe case STILL lands a real rewrite — and with a double-quoted literal
    # no longer injects orphan imports (the F401 the audit found).
    out = _landed_content(
        tmp_path, "app/m.py",
        'import os\nos.system("ls -la")\n',
        "os.system")
    assert 'subprocess.run(shlex.split("ls -la"), check=True)' in out
    assert "import subprocess" in out
    assert "import shlex" in out


def test_os_system_bare_discarded_still_landable(tmp_path: Path):
    # No over-refusal: the canonical safe os.system case remains a landable finding.
    _own_project(tmp_path, "app/m.py", "import os\ndef f(cmd):\n    os.system(cmd)\n")
    assert ("app/m.py", "os.system") in _landable(str(tmp_path))
