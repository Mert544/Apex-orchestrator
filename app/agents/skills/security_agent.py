from __future__ import annotations

"""SecurityAgent — AST-based security risk detector with auto-tuning."""

import ast
import re
from pathlib import Path
from typing import Any

from app.agents.base import Agent
from app.agents.learning import AgentLearning


class SecurityAgent(Agent):
    """Agent: scans code for security anti-patterns with auto-tuning."""

    CRITICAL_PATTERNS = {
        "eval": ("eval() usage", "critical", "Replace with ast.literal_eval or json.loads"),
        "exec": ("exec() usage", "critical", "Avoid dynamic code execution"),
        "compile": ("compile() usage", "high", "Validate all inputs to compile()"),
        "os.system": ("os.system() shell injection", "critical", "Use subprocess.run with shell=False"),
        "subprocess.call": ("subprocess.call()", "high", "Use subprocess.run with shell=False"),
        "pickle.loads": ("pickle deserialization", "critical", "Use json or msgpack instead"),
        "yaml.load": ("yaml unsafe load", "high", "Use yaml.safe_load"),
        "yaml.unsafe_load": ("yaml unsafe load", "critical", "Use yaml.safe_load"),
    }

    SECRET_PATTERNS = [
        (r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']+["\']', "hardcoded_password", "high"),
        (r'(?:api_key|apikey|auth_token|access_token|secret_key|client_secret)\s*=\s*["\'][^"\']+["\']', "hardcoded_secret", "high"),
        (r'(?:database_url|db_url|connection_string)\s*=\s*["\'][^"\']+["\']', "hardcoded_connection", "medium"),
    ]
    SECRET_EXCLUDE_VALUES = {"", "local", "test", "example", "your_key_here", "config.get"}

    def __init__(self, name: str = "security", learning: AgentLearning | None = None, **kwargs: Any) -> None:
        super().__init__(name=name, role="security_auditor", **kwargs)
        self.project_root: Path | None = None
        self.learning = learning
        # Instance-level copy to avoid mutating class variable
        self.patterns = dict(self.CRITICAL_PATTERNS)
        self._apply_learned_tuning()

    def _apply_learned_tuning(self) -> None:
        """Adjust patterns based on past performance."""
        if self.learning is None:
            return
        for pattern_name in list(self.patterns.keys()):
            if self.learning.should_skip("security", pattern_name, min_ema=0.3):
                self.patterns.pop(pattern_name, None)

    def record_result(self, pattern: str, success: bool) -> None:
        """Record whether a detection was correct (for learning)."""
        if self.learning:
            self.learning.record_result("security", pattern, success)

    def _execute(self, project_root: str | Path = ".", **kwargs: Any) -> dict[str, Any]:
        root = Path(project_root).resolve()
        self.project_root = root
        findings: list[dict[str, Any]] = []

        files = self._discover_files(root)
        for rel_path in files:
            full = root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            findings.extend(self._scan_ast(rel_path, source))
            findings.extend(self._scan_regex(rel_path, source))

        self.send(
            topic="security.scan.complete",
            payload={"findings_count": len(findings), "risk_score": self._calc_score(findings)},
        )

        return {
            "agent": self.name,
            "role": self.role,
            "scanned_files": len(files),
            "findings_count": len(findings),
            "risk_score": self._calc_score(findings),
            "findings": findings,
        }

    def _discover_files(self, root: Path) -> list[str]:
        skipped = {"examples", "tests", "test", "validation", "__pycache__", ".git", ".apex", ".epistemic"}
        return [
            str(p.relative_to(root).as_posix())
            for p in root.rglob("*.py")
            if not any(part in skipped for part in p.parts)
        ]

    def _scan_ast(self, rel_path: str, source: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                findings.extend(self._check_call(rel_path, node, source))
            elif isinstance(node, ast.ExceptHandler) and node.type is None:
                line = getattr(node, "lineno", 1)
                findings.append(
                    {
                        "file": rel_path,
                        "line": line,
                        "risk_type": "bare_except",
                        "severity": "medium",
                        "details": f"Bare except clause at line {line}",
                        "suggestion": "Use 'except Exception:' or specific exceptions",
                    }
                )
        return findings

    def _check_call(self, rel_path: str, node: ast.Call, source: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        func_name = self._get_call_name(node)
        if not func_name:
            return findings

        for pattern, (risk_type, severity, suggestion) in self.patterns.items():
            # Exact match: either direct call (eval) or method call (obj.eval)
            is_match = func_name == pattern or func_name.endswith("." + pattern)
            if is_match:
                # False positive filters
                if pattern == "compile" and any(safe in func_name for safe in ("re.compile", "regex.compile")):
                    continue
                if pattern == "eval" and "literal_eval" in func_name:
                    continue
                line = getattr(node, "lineno", 1)
                findings.append(
                    {
                        "file": rel_path,
                        "line": line,
                        "risk_type": risk_type,
                        "severity": severity,
                        "details": f"Detected {pattern} at line {line}",
                        "suggestion": suggestion,
                    }
                )

        for arg in node.args:
            if isinstance(arg, ast.JoinedStr) and any(sql in func_name for sql in ("execute", "cursor")):
                line = getattr(arg, "lineno", 1)
                findings.append(
                    {
                        "file": rel_path,
                        "line": line,
                        "risk_type": "sql_injection",
                        "severity": "critical",
                        "details": f"f-string used in SQL query at line {line}",
                        "suggestion": "Use parameterized queries",
                    }
                )
        return findings

    def _scan_regex(self, rel_path: str, source: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        lines = source.splitlines()
        for line_no, line in enumerate(lines, 1):
            for pattern, risk_type, severity in self.SECRET_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    # Extract assigned value for exclusion check
                    value_match = re.search(r'=\s*["\']([^"\']+)["\']', line)
                    if value_match:
                        value = value_match.group(1).strip().lower()
                        if value in self.SECRET_EXCLUDE_VALUES:
                            continue
                        # Skip config.get() patterns
                        if "config.get" in line or "os.environ" in line:
                            continue
                    findings.append(
                        {
                            "file": rel_path,
                            "line": line_no,
                            "risk_type": risk_type,
                            "severity": severity,
                            "details": f"Potential hardcoded secret at line {line_no}",
                            "suggestion": "Use environment variables or secret managers",
                        }
                    )
        return findings

    def _get_call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            parts = []
            current = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""

    def _calc_score(self, findings: list[dict[str, Any]]) -> float:
        weights = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}
        total = sum(weights.get(f.get("severity", "low"), 0.1) for f in findings)
        return round(min(total / 5.0, 1.0), 2)
