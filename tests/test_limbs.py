import os
import tempfile
import shutil
from pathlib import Path

from app.agents.limbs import (
    Limb,
    DebugLimb,
    CoverageLimb,
    RefactorLimb,
    DependencyLimb,
    DocLimb,
    CILimb,
    get_limb,
    list_limbs,
)


class TestLimbBase:
    def test_limb_base_initialization(self):
        limb = Limb(name="test-limb", role="tester")
        assert limb.name == "test-limb"
        assert limb.role == "tester"
        assert limb.last_execution_result == {}

    def test_limb_can_run_default(self):
        limb = Limb(name="test", role="test")
        assert limb.can_run() is True

    def test_limb_get_requirements(self):
        limb = Limb(name="test", role="test")
        reqs = limb.get_requirements()
        assert "files" in reqs
        assert "tools" in reqs
        assert "permissions" in reqs


class TestDebugLimb:
    def test_debug_limb_creation(self):
        limb = DebugLimb()
        assert limb.name == "debug-limb"
        assert limb.role == "debugger"

    def test_debug_limb_execute_no_error(self):
        limb = DebugLimb()
        result = limb.run(project_root="/test", target_file="main.py", error_trace="")
        assert result["limb"] == "debug"

    def test_debug_limb_analyze_traceback(self):
        limb = DebugLimb()
        cause = limb._analyze_traceback("NameError: name 'foo' is not defined", "/test")
        assert cause is not None
        assert cause["type"] == "NameError"


class TestCoverageLimb:
    def test_coverage_limb_creation(self):
        limb = CoverageLimb()
        assert limb.name == "coverage-limb"
        assert limb.role == "coverage_analyzer"

    def test_coverage_limb_execute(self):
        limb = CoverageLimb()
        result = limb.run(project_root="/test", min_coverage=80.0)
        assert result["limb"] == "coverage"
        assert "current_coverage" in result


class TestRefactorLimb:
    def test_refactor_limb_creation(self):
        limb = RefactorLimb()
        assert limb.name == "refactor-limb"
        assert limb.role == "refactorer"

    def test_refactor_limb_execute(self):
        limb = RefactorLimb()
        result = limb.run(project_root="/test", target_pattern="long_function")
        assert result["limb"] == "refactor"
        assert "issues_found" in result


class TestDependencyLimb:
    def test_dependency_limb_creation(self):
        limb = DependencyLimb()
        assert limb.name == "dependency-limb"
        assert limb.role == "dependency_manager"

    def test_dependency_limb_execute(self):
        limb = DependencyLimb()
        result = limb.run(project_root="/test", check_outdated=True)
        assert result["limb"] == "dependency"
        assert "outdated_packages" in result


class TestDocLimb:
    def test_doc_limb_creation(self):
        limb = DocLimb()
        assert limb.name == "doc-limb"
        assert limb.role == "documenter"

    def test_doc_limb_execute(self):
        limb = DocLimb()
        result = limb.run(project_root="/test", target="api")
        assert result["limb"] == "documentation"
        assert "generated_docs" in result


class TestCILimb:
    def test_ci_limb_creation(self):
        limb = CILimb()
        assert limb.name == "ci-limb"
        assert limb.role == "ci_runner"

    def test_ci_limb_execute(self):
        limb = CILimb()
        result = limb.run(project_root="/test", pipeline="default")
        assert result["limb"] == "ci"
        assert "stages" in result
        assert "passed" in result


class TestLimbFactory:
    def test_get_limb_debug(self):
        limb = get_limb("debug")
        assert isinstance(limb, DebugLimb)

    def test_get_limb_coverage(self):
        limb = get_limb("coverage")
        assert isinstance(limb, CoverageLimb)

    def test_get_limb_unknown_raises(self):
        import pytest

        with pytest.raises(ValueError):
            get_limb("unknown")

    def test_list_limbs(self):
        limbs = list_limbs()
        assert "debug" in limbs
        assert "coverage" in limbs
        assert "refactor" in limbs
        assert "ci" in limbs


class TestLimbWithRealCode:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.tmp_dir)

    def teardown_method(self):
        os.chdir(self.original_dir)
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except:
            pass

    def test_refactor_limb_finds_long_functions(self):
        (Path(self.tmp_dir) / "sample.py").write_text("""
def long_function():
    x = 1
    x = 2
    x = 3
    x = 4
    x = 5
    x = 6
    x = 7
    x = 8
    x = 9
    x = 10
    x = 11
    x = 12
    x = 13
    x = 14
    x = 15
    x = 16
    x = 17
    x = 18
    x = 19
    x = 20
    x = 21
    x = 22
    x = 23
    x = 24
    x = 25
    x = 26
    x = 27
    x = 28
    x = 29
    x = 30
    x = 31
    x = 32
    x = 33
    x = 34
    x = 35
    x = 36
    x = 37
    x = 38
    x = 39
    x = 40
    x = 41
    x = 42
    x = 43
    x = 44
    x = 45
    x = 46
    x = 47
    x = 48
    x = 49
    x = 50
    return x
""")
        limb = RefactorLimb()
        result = limb.run(project_root=self.tmp_dir)
        assert len(result["issues_found"]) > 0

    def test_debug_limb_finds_eval(self):
        (Path(self.tmp_dir) / "unsafe.py").write_text("def foo():\n    eval('1+1')\n")
        limb = DebugLimb()
        result = limb.run(project_root=self.tmp_dir, target_file="unsafe.py")
        assert any("eval" in a for a in result["analysis"])
