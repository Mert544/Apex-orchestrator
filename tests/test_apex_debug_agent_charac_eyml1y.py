"""Characterization harness: proves the refactored ApexDebugAgent.run is
byte-identical to the pre-refactor original across every branch.

The original implementation is loaded from a frozen snapshot of HEAD's version
of the file (captured at /tmp by the refactor session). The refactored version
is the live module. Both are exercised with the same inputs and their full
output is compared field-by-field (excluding the inherently timing-dependent
``duration_ms``, which is computed identically in both).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REFAC = importlib.import_module("app.agents.skills.apex_debug_agent")

_ORIG_SNAPSHOT = Path("/tmp/apex_debug_agent_ORIG.py")


def _load_original():
    if not _ORIG_SNAPSHOT.exists():
        pytest.skip("original snapshot not available")
    spec = importlib.util.spec_from_file_location(
        "apex_debug_agent_ORIG_eyml1y", _ORIG_SNAPSHOT
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ORIG = _load_original()


class _FakeSecurityAgent:
    """Deterministic stand-in for SecurityAgent, scripted per-test."""

    scan = {}
    raise_exc = None

    def run(self, project_root):
        if self.raise_exc is not None:
            raise self.raise_exc
        return type(self).scan


def _normalize(result):
    """Reduce an AgentAnalysisResult to a stable comparable structure."""
    return {
        "files_analyzed": result.files_analyzed,
        "errors": list(result.errors),
        "findings": [
            (
                f.title,
                f.message,
                f.category,
                int(f.severity),
                f.file,
                f.line,
                f.confidence,
            )
            for f in result.findings
        ],
    }


def _run_both(monkeypatch, *, project_root, min_severity, scan, raise_exc, run_kwargs):
    """Run both module versions with identical scripted dependencies."""
    fake_cls = type(
        "FakeSA", (_FakeSecurityAgent,), {"scan": scan, "raise_exc": raise_exc}
    )
    outputs = []
    for mod in (ORIG, REFAC):
        # Patch the SecurityAgent symbol imported lazily inside run().
        import app.agents.skills.security_agent as sa_mod

        monkeypatch.setattr(sa_mod, "SecurityAgent", fake_cls, raising=False)
        agent = mod.ApexDebugAgent(project_root, min_severity=min_severity)
        outputs.append(_normalize(agent.run(**run_kwargs)))
    return outputs


# A broad matrix of raw findings exercising every fallback branch.
_RAW_VARIANTS = [
    {"severity": "critical", "risk_type": "RT", "details": "D", "file": "a.py", "line": 5},
    {"severity": "HIGH", "risk": "R", "suggestion": "S", "file": "b.py", "line": "9"},
    {"severity": "medium", "details": "only-details"},
    {"severity": "low", "suggestion": "only-suggestion"},
    {"severity": "bogus", "file": "c.py"},  # unknown sev -> LOW, title -> "issue"
    {},  # empty -> sev LOW, title "issue", message ""
    {"severity": "info", "risk_type": "info-rt"},  # info maps to LOW via default
    {"severity": "Critical", "risk_type": "", "risk": "fallback-risk"},  # empty title chain
    {"severity": "high", "line": 0, "file": ""},
    {"severity": "high", "line": None},  # None line -> 0
]


@pytest.mark.parametrize("min_severity", ["info", "low", "medium", "high", "critical", "weird"])
def test_byte_identical_findings_matrix(monkeypatch, tmp_path, min_severity):
    scan = {"findings": _RAW_VARIANTS, "scanned_files": 7}
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity=min_severity,
        scan=scan,
        raise_exc=None,
        run_kwargs={},
    )
    assert orig_out == refac_out


@pytest.mark.parametrize(
    "categories",
    [None, [], ["security"], ["other"], ["security", "other"], ["x", "y"]],
)
def test_byte_identical_category_filter(monkeypatch, tmp_path, categories):
    scan = {"findings": _RAW_VARIANTS, "scanned_files": 3}
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity="low",
        scan=scan,
        raise_exc=None,
        run_kwargs={"categories": categories},
    )
    assert orig_out == refac_out


@pytest.mark.parametrize("scanned", [0, None, 4, "12"])
def test_byte_identical_scanned_files_coercion(monkeypatch, tmp_path, scanned):
    scan = {"findings": [], "scanned_files": scanned}
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity="low",
        scan=scan,
        raise_exc=None,
        run_kwargs={},
    )
    assert orig_out == refac_out


def test_byte_identical_empty_scan(monkeypatch, tmp_path):
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity="low",
        scan={},  # no "findings"/"scanned_files" keys at all
        raise_exc=None,
        run_kwargs={},
    )
    assert orig_out == refac_out


def test_byte_identical_scan_exception(monkeypatch, tmp_path):
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity="low",
        scan={},
        raise_exc=ValueError("boom"),
        run_kwargs={},
    )
    assert orig_out == refac_out
    assert orig_out["errors"] == ["Analysis failed: boom"]


def test_byte_identical_missing_target(monkeypatch, tmp_path):
    # target that does not exist as-is nor under project_root.
    missing = "definitely_no_such_path_eyml1y"
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity="low",
        scan={"findings": _RAW_VARIANTS, "scanned_files": 1},
        raise_exc=None,
        run_kwargs={"target": missing},
    )
    assert orig_out == refac_out
    assert orig_out["errors"][0].startswith(f"Target '{missing}' not found")


def test_byte_identical_target_relative_to_root(monkeypatch, tmp_path):
    # target exists only relative to project_root -> resolved via fallback branch.
    (tmp_path / "sub").mkdir()
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity="low",
        scan={"findings": _RAW_VARIANTS, "scanned_files": 2},
        raise_exc=None,
        run_kwargs={"target": "sub"},
    )
    assert orig_out == refac_out
    assert orig_out["errors"] == []


def test_byte_identical_absolute_existing_target(monkeypatch, tmp_path):
    d = tmp_path / "abs"
    d.mkdir()
    orig_out, refac_out = _run_both(
        monkeypatch,
        project_root=tmp_path,
        min_severity="medium",
        scan={"findings": _RAW_VARIANTS, "scanned_files": 5},
        raise_exc=None,
        run_kwargs={"target": str(d)},
    )
    assert orig_out == refac_out
