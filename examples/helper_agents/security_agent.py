from __future__ import annotations

"""
SecurityAgent — AST-based security risk detector for Python codebases.

Scans Python files for:
- eval(), exec(), compile() usage
- os.system(), subprocess.call() with shell=True
- pickle.loads(), yaml.unsafe_load()
- Hardcoded secrets (basic regex patterns)
- SQL string formatting (f-string SQL)
- Bare except clauses
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SecurityFinding:
    file: str
    line: int
    risk_type: str
    severity: str  # critical | high | medium | low
    details: str
    suggestion: str


@dataclass
class SecurityReport:
    findings: list[SecurityFinding] = field(default_factory=list)
    scanned_files: int = 0
    risk_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_files": self.scanned_files,
            "risk_score": round(self.risk_score, 2),
            "findings_count": len(self.findings),
            "findings": [
                {
                    "file": f.file,
                    "line": f.line,
                    "risk_type": f.risk_type,
                    "severity": f.severity,
                    "details": f.details,
                    "suggestion": f.suggestion,
                }
                for f in self.findings
            ],
        }


class SecurityAgent:
    """Helper agent: scans code for security anti-patterns."""

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
        (r'(?:api_key|apikey|token|secret)\s*=\s*["\'][^"\']+["\']', "hardcoded_secret", "high"),
        (r'(?:database_url|db_url|connection_string)\s*=\s*["\'][^"\']+["\']', "hardcoded_connection", "medium"),
    ]

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.report = SecurityReport()

    def scan(self, target_files: list[str] | None = None) -> SecurityReport:
        files = self._discover_files(target_files)
        self.report.scanned_files = len(files)

        for rel_path in files:
            full = self.root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            self._scan_ast(rel_path, source)
            self._scan_regex(rel_path, source)

        self._calculate_risk_score()
        return self.report

    def _discover_files(self, target_files: list[str] | None = None) -> list[str]:
        if target_files:
            return target_files
        return [
            str(p.relative_to(self.root).as_posix())
            for p in self.root.rglob("*.py")
            if ".apex" not in p.parts and "__pycache__" not in p.parts
        ]

    def _scan_ast(self, rel_path: str, source: str) -> None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                self._check_call_node(rel_path, node, source)
            elif isinstance(node, ast.ExceptHandler):
                self._check_except_handler(rel_path, node)

    def _check_call_node(self, rel_path: str, node: ast.Call, source: str) -> None:
        func_name = self._get_call_name(node)
        if not func_name:
            return

        for pattern, (risk_type, severity, suggestion) in self.CRITICAL_PATTERNS.items():
            if pattern in func_name:
                line = getattr(node, "lineno", 1)
                self.report.findings.append(
                    SecurityFinding(
                        file=rel_path,
                        line=line,
                        risk_type=risk_type,
                        severity=severity,
                        details=f"Detected {pattern} at line {line}",
                        suggestion=suggestion,
                    )
                )

        # SQL injection via f-string
        if any(sql in func_name for sql in ("execute", "executemany", "cursor")):
            for arg in node.args:
                if isinstance(arg, ast.JoinedStr):
                    line = getattr(arg, "lineno", 1)
                    self.report.findings.append(
                        SecurityFinding(
                            file=rel_path,
                            line=line,
                            risk_type="sql_injection",
                            severity="critical",
                            details=f"f-string used in SQL query at line {line}",
                            suggestion="Use parameterized queries",
                        )
                    )

    def _check_except_handler(self, rel_path: str, node: ast.ExceptHandler) -> None:
        if node.type is None:
            line = getattr(node, "lineno", 1)
            self.report.findings.append(
                SecurityFinding(
                    file=rel_path,
                    line=line,
                    risk_type="bare_except",
                    severity="medium",
                    details=f"Bare except clause at line {line}",
                    suggestion="Use 'except Exception:' or specific exceptions",
                )
            )

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

    def _scan_regex(self, rel_path: str, source: str) -> None:
        lines = source.splitlines()
        for line_no, line in enumerate(lines, 1):
            for pattern, risk_type, severity in self.SECRET_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    self.report.findings.append(
                        SecurityFinding(
                            file=rel_path,
                            line=line_no,
                            risk_type=risk_type,
                            severity=severity,
                            details=f"Potential hardcoded secret at line {line_no}",
                            suggestion="Use environment variables or secret managers",
                        )
                    )

    def _calculate_risk_score(self) -> None:
        severity_weights = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}
        total = sum(severity_weights.get(f.severity, 0.1) for f in self.report.findings)
        self.report.risk_score = min(total / 5.0, 1.0)  # Cap at 1.0


# Plugin registration
__plugin_name__ = "security_agent"

def register(proxy):
    agent = SecurityAgent(proxy.get("project_root", "."))
    proxy.add_hook("before_scan", lambda ctx: agent.scan())
