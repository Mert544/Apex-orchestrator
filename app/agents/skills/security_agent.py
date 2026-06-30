from __future__ import annotations

"""SecurityAgent — AST-based security risk detector with auto-tuning."""

import ast
import re
from pathlib import Path
from typing import Any

from app.agents.base import Agent
from app.agents.learning import AgentLearning
from app.engine import detectors
from app.engine.skip_dirs import iter_source_files


# Maps a detect() security Issue's fix_kind (the rich engine's routing label) to
# the risk_type slug surfaced in the agent's finding dict, so `scan` reads in the
# agent's own vocabulary. fix_kinds absent here (or empty, e.g. exec/marshal) fall
# back to a slug derived from the label — never dropped, so scan stays a superset.
_DETECT_RISK_TYPE = {
    "eval": "eval_usage",
    "os.system": "os_system_shell_injection",
    "os.popen": "os_popen_shell_injection",
    "pickle": "pickle_deserialization",
    "subprocess-shell-literal": "subprocess_shell_injection",
    "tls-verify": "tls_verification_disabled",
    "zip-slip": "path_traversal",
    "yaml": "yaml_unsafe_load",
    "sql": "sql_injection",
    "tempfile": "insecure_tempfile",
    "weak-hash": "weak_hash",
    "hashlib-new-weak": "weak_hash",
    "bare except": "bare_except",
    "base-exception": "broad_exception",
}

# Canonical risk token for de-duplication. Both a legacy finding's risk_type and a
# mapped detect finding's risk_type collapse to one of these tokens so the SAME
# logical risk on the SAME line, flagged by both engines, is reported only once.
# Order matters: the first substring that matches wins.
_RISK_CANON = (
    ("sql", "sql"),
    ("eval", "eval"),
    ("exec", "exec"),
    ("compile", "exec"),
    ("os_system", "os.system"),
    ("os.system", "os.system"),
    ("os_popen", "os.popen"),
    ("os.popen", "os.popen"),
    ("pickle", "pickle"),
    ("yaml", "yaml"),
    ("tls", "tls"),
    ("traversal", "zip-slip"),
    ("zip", "zip-slip"),
    ("tempfile", "tempfile"),
    ("weak_hash", "weak-hash"),
    ("hash", "weak-hash"),
    ("subprocess", "subprocess"),
    ("bare_except", "bare-except"),
    ("broad_exception", "base-exception"),
    ("hardcoded", "secret"),
    ("secret", "secret"),
    ("connection", "secret"),
    ("password", "secret"),
)

# detect()'s severities are high|medium|low; the agent additionally uses
# "critical" for its top tier. The mapping below keeps detect findings inside the
# agent's existing severity vocabulary so _calc_score weights them unchanged.
_DETECT_SEVERITY = {"high": "high", "medium": "medium", "low": "low"}

# Some security Issues carry no fix_kind (exec, pickle.load catch-all, marshal,
# shell=True, hardcoded secret). Derive their risk_type from a message substring
# so they canonicalise alongside the legacy findings and never produce a stray
# second finding for the same risk on the same line. First match wins.
_DETECT_MESSAGE_RISK = (
    ("exec()", "exec_usage"),
    ("pickle.load", "pickle_deserialization"),
    ("marshal.load", "unsafe_deserialization"),
    ("shell=True", "subprocess_shell_injection"),
    ("hardcoded secret", "hardcoded_secret"),
)


def _canonical_risk(risk_type: str) -> str:
    """A coarse risk token for dedup; falls back to the raw risk_type."""
    rt = risk_type.lower()
    for needle, token in _RISK_CANON:
        if needle in rt:
            return token
    return rt


def _detect_finding(rel_path: str, issue: detectors.Issue) -> dict[str, Any]:
    """Map a detect() security Issue into the agent's existing finding schema.

    Preserves the dict shape every downstream consumer reads (file/line/risk_type/
    severity/details/suggestion). The detect message is carried verbatim in
    ``details`` so the finding stays traceable to the rich engine.
    """
    risk_type = _DETECT_RISK_TYPE.get(issue.fix_kind)
    if risk_type is None and issue.fix_kind:
        risk_type = issue.fix_kind.replace("-", "_").replace(".", "_")
    if risk_type is None:
        # No fix_kind: derive a risk_type from the message so the finding still
        # canonicalises alongside the legacy ones (no stray same-line duplicate).
        for needle, slug in _DETECT_MESSAGE_RISK:
            if needle in issue.message:
                risk_type = slug
                break
    if risk_type is None:
        risk_type = "security_issue"
    return {
        "file": rel_path,
        "line": issue.line,
        "risk_type": risk_type,
        "severity": _DETECT_SEVERITY.get(issue.severity, "low"),
        "details": issue.message,
        "suggestion": issue.message,
    }


def _has_shell_true(node: ast.Call) -> bool:
    """True if the call passes shell=True (the actual injection risk)."""
    return any(
        kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in node.keywords
    )


def _call_pattern_matches(func_name: str, pattern: str) -> bool:
    """Whether a resolved call name matches a configured sink pattern.

    Module-qualified sinks (``os.system``, ``pickle.loads``) match the dotted
    name or any attribute path ending in it; a bare builtin (``eval``) matches
    only an exact name so unrelated methods like ``model.compile()`` are skipped.
    """
    if "." in pattern:
        return func_name == pattern or func_name.endswith("." + pattern)
    return func_name == pattern


def _call_is_false_positive(pattern: str, func_name: str, node: ast.Call) -> bool:
    """Whether a matched sink is a known-safe usage that must not be flagged."""
    if pattern == "compile" and any(safe in func_name for safe in ("re.compile", "regex.compile")):
        return True
    if pattern == "eval" and "literal_eval" in func_name:
        return True
    return pattern == "subprocess.call" and not _has_shell_true(node)


def _sink_finding(rel_path: str, node: ast.Call, pattern: str, risk_type: str, severity: str, suggestion: str) -> dict[str, Any]:
    """Build the finding dict for a matched dangerous sink call."""
    line = getattr(node, "lineno", 1)
    return {
        "file": rel_path,
        "line": line,
        "risk_type": risk_type,
        "severity": severity,
        "details": f"Detected {pattern} at line {line}",
        "suggestion": suggestion,
    }


def _bare_except_finding(rel_path: str, node: ast.ExceptHandler) -> dict[str, Any]:
    """Build the finding dict for a bare ``except:`` clause."""
    line = getattr(node, "lineno", 1)
    return {
        "file": rel_path,
        "line": line,
        "risk_type": "bare_except",
        "severity": "medium",
        "details": f"Bare except clause at line {line}",
        "suggestion": "Use 'except Exception:' or specific exceptions",
    }


def _joinedstr_has_nonliteral(node: ast.JoinedStr) -> bool:
    """True if an f-string interpolates a non-constant value (the injection risk).

    ``f"static text"`` (no ``FormattedValue``) is a plain literal and is *not* a
    SQL-injection risk; only an f-string that splices a runtime expression is.
    """
    return any(isinstance(v, ast.FormattedValue) for v in node.values)


def _is_string_concat_binop(node: ast.expr) -> bool:
    """True if ``node`` is a string ``+``/``%`` BinOp that mixes in a non-literal.

    Catches ``"SELECT ... " + user`` and ``"SELECT ... %s" % user`` — the classic
    pre-f-string injection shapes. A literal-only expression (``"a" + "b"``) is
    NOT flagged. The operand chain must contain at least one string Constant (so a
    pure ``a + b`` numeric add does not match) and at least one non-Constant part
    (the tainted value). Conservative and deterministic.
    """
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod))):
        return False
    has_str_literal = False
    has_nonliteral = False
    stack: list[ast.expr] = [node.left, node.right]
    while stack:
        part = stack.pop()
        if isinstance(part, ast.BinOp) and isinstance(part.op, (ast.Add, ast.Mod)):
            stack.append(part.left)
            stack.append(part.right)
        elif isinstance(part, ast.Constant):
            if isinstance(part.value, str):
                has_str_literal = True
        elif isinstance(part, ast.JoinedStr):
            has_str_literal = True
            if _joinedstr_has_nonliteral(part):
                has_nonliteral = True
        else:
            has_nonliteral = True
    return has_str_literal and has_nonliteral


def _expr_is_tainted_sql(node: ast.expr) -> bool:
    """True if an expression building a SQL string carries a non-literal part.

    The unified risk predicate shared by the inline and the variable-resolved
    paths: an f-string with an interpolation, or a string ``+``/``%`` concat that
    mixes a literal with a runtime value.
    """
    if isinstance(node, ast.JoinedStr):
        return _joinedstr_has_nonliteral(node)
    return _is_string_concat_binop(node)


def _resolve_sql_assignment(
    name: str, call_line: int, assignments: dict[str, list[tuple[int, ast.expr]]]
) -> ast.expr | None:
    """The nearest prior assignment value for ``name`` before ``call_line``, if any.

    ``assignments[name]`` is a line-sorted list of ``(lineno, value_expr)``. We
    return the value of the last assignment whose line is < ``call_line`` so a
    later reassignment does not mask an earlier safe/unsafe binding. ``None`` when
    the name has no prior binding in scope.
    """
    candidates = assignments.get(name)
    if not candidates:
        return None
    chosen: ast.expr | None = None
    for lineno, value in candidates:
        if lineno < call_line:
            chosen = value
        else:
            break
    return chosen


def _sql_injection_findings(
    rel_path: str,
    node: ast.Call,
    func_name: str,
    assignments: dict[str, list[tuple[int, ast.expr]]] | None = None,
) -> list[dict[str, Any]]:
    """Findings for unsafe SQL strings passed to execute()/cursor() calls.

    Flags three shapes feeding a SQL-exec sink, all FLAG-ONLY (human review):
      1. an inline f-string argument with an interpolation,
      2. an inline string ``+``/``%`` concatenation mixing a literal and a value,
      3. a ``Name`` argument whose nearest prior in-scope assignment is one of the
         above (assigned-then-passed).

    A parameterized query (``execute("... ?", (var,))`` — a plain string literal +
    a params tuple) is never flagged. ``assignments`` maps a variable name to its
    line-sorted ``(lineno, value)`` bindings in the enclosing module scope.
    """
    findings: list[dict[str, Any]] = []
    if not any(sql in func_name for sql in ("execute", "cursor")):
        return findings
    assignments = assignments or {}
    for arg in node.args:
        risk_node: ast.expr | None = None
        details: str | None = None
        if isinstance(arg, ast.JoinedStr) and _joinedstr_has_nonliteral(arg):
            risk_node = arg
            details = "f-string used in SQL query at line {line}"
        elif _is_string_concat_binop(arg):
            risk_node = arg
            details = "string concatenation/format used in SQL query at line {line}"
        elif isinstance(arg, ast.Name):
            resolved = _resolve_sql_assignment(arg.id, getattr(node, "lineno", 1), assignments)
            if resolved is not None and _expr_is_tainted_sql(resolved):
                risk_node = arg
                details = "interpolated/concatenated string variable used in SQL query at line {line}"
        if risk_node is None or details is None:
            continue
        line = getattr(risk_node, "lineno", 1)
        findings.append(
            {
                "file": rel_path,
                "line": line,
                "risk_type": "sql_injection",
                "severity": "critical",
                "details": details.format(line=line),
                "suggestion": "Use parameterized queries",
            }
        )
    return findings


_SUPPRESS_RE = re.compile(r"#\s*(noqa|nosec)\b(?:\s*[:=]\s*([A-Za-z0-9 ,]+))?", re.IGNORECASE)


def _line_suppresses(line: str, risk_type: str) -> bool:
    """Respect inline security-suppression comments the way Bandit/ruff do.

    A mature project explicitly annotates intentional risks; a grade must honor
    that acknowledgement rather than re-flag it. We suppress on:
      - ``# nosec`` (Bandit's security suppression — unambiguous),
      - a bare ``# noqa`` (disables all lint on the line),
      - ``# noqa: S###`` (ruff's flake8-bandit security codes, e.g. S307 eval,
        S605 os.system, S301 pickle, S105 hardcoded password), and
      - ``# noqa: E722`` for a bare-except finding (that is its own code).
    Unrelated suppressions (E501, F401, bugbear B###) are NOT treated as
    security acknowledgements.
    """
    m = _SUPPRESS_RE.search(line)
    if not m:
        return False
    directive = m.group(1).lower()
    if directive == "nosec":
        return True
    codes_raw = m.group(2)
    if not codes_raw:  # a bare directive (no codes) disables all lint on the line
        return True
    codes = {c.strip().upper() for c in codes_raw.replace(",", " ").split()}
    if any(c[:1] == "S" and c[1:].isdigit() for c in codes):
        return True
    return bool(risk_type == "bare_except" and "E722" in codes)


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
        if not (self.learning):
            return
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
            legacy = self._scan_ast(rel_path, source) + self._scan_regex(rel_path, source)
            findings.extend(self._merge_detect(rel_path, source, legacy))

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

    def _merge_detect(
        self, rel_path: str, source: str, legacy: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Legacy findings PLUS the rich detect() engine's security issues.

        Makes the per-file scan a SUPERSET of today's legacy scan and consistent
        with ``grade``/``maintain`` (which both read ``detectors.detect``). Each
        ``category=="security"`` Issue is mapped into the agent's finding schema
        and merged, de-duplicated so the SAME risk on the SAME line — flagged by
        both engines — is reported only once (by ``(line, canonical-risk)``), and
        identical detect findings collapse by ``(line, details)``. The result is
        sorted by ``(line, details)`` for determinism.

        Best-effort: if ``detect`` raises on this file we fall back to the legacy
        findings for it, never crashing the scan.
        """
        try:
            issues = detectors.detect(source)
        except Exception:
            return list(legacy)

        # Lines+risks already covered by a legacy finding: a detect finding for
        # the same (line, canonical risk) is the same issue, not a second one.
        legacy_keys = {(f["line"], _canonical_risk(str(f.get("risk_type", "")))) for f in legacy}
        merged = list(legacy)
        seen_detail: set[tuple[int, str]] = {(f["line"], f.get("details", "")) for f in legacy}
        for issue in issues:
            if issue.category != "security":
                continue
            finding = _detect_finding(rel_path, issue)
            key = (finding["line"], _canonical_risk(finding["risk_type"]))
            if key in legacy_keys:
                continue
            detail_key = (finding["line"], finding["details"])
            if detail_key in seen_detail:
                continue
            seen_detail.add(detail_key)
            merged.append(finding)
        # Apply the agent's OWN inline-suppression filter to the merged set. The
        # legacy findings were already filtered in ``_scan_*`` (idempotent here),
        # but the detect()-derived additions were not — and the rich engine no
        # longer treats a ruff/Bandit ``# noqa: S###`` as a security opt-out (that
        # footgun was closed for grade/harden). The agent KEEPS its documented
        # ``# noqa: S###`` acknowledgement behaviour (mature projects like scrapy),
        # so it must re-apply ``_line_suppresses`` to whatever detect() surfaced.
        merged = self._drop_suppressed(merged, source)
        merged.sort(key=lambda f: (f["line"], str(f.get("details", ""))))
        return merged

    def _discover_files(self, root: Path) -> list[str]:
        skipped = {"tests", "test", "validation"}
        return [
            str(p.relative_to(root).as_posix())
            for p in iter_source_files(root)
            if not any(part in skipped for part in p.relative_to(root).parts)
        ]

    def _nested_compile_ids(self, tree: ast.AST) -> set[int]:
        """ids of ``compile()`` calls passed directly to ``eval()``/``exec()``.

        A compile() that is a direct argument to eval()/exec() is the *same*
        dynamic-execution risk already reported for the eval/exec — not a
        second one. Without this, `eval(compile(...))` / `exec(compile(...))`
        (idiomatic config/startup loading in Flask, etc.) double-counts.
        """
        nested: set[int] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and self._get_call_name(node) in ("eval", "exec")):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Call) and self._get_call_name(arg) == "compile":
                    nested.add(id(arg))
        return nested

    def _collect_assignments(self, tree: ast.AST) -> dict[str, list[tuple[int, ast.expr]]]:
        """Map each assigned simple name to its line-sorted ``(lineno, value)`` list.

        Powers the assigned-f-string/concat-then-execute SQL-injection shape: when
        a ``Name`` is the execute() argument we look up its nearest prior binding.
        Only simple ``x = <expr>`` targets are recorded (no tuple/attr targets);
        bindings are sorted by line so resolution is deterministic. Scope is the
        whole module — a deliberate, conservative over-approximation that keeps the
        detector simple and never silently misses a same-name binding.
        """
        assignments: dict[str, list[tuple[int, ast.expr]]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append((getattr(node, "lineno", 0), node.value))
        for bindings in assignments.values():
            bindings.sort(key=lambda b: b[0])
        return assignments

    def _scan_node(
        self,
        rel_path: str,
        source: str,
        node: ast.AST,
        nested_compiles: set[int],
        assignments: dict[str, list[tuple[int, ast.expr]]],
    ) -> list[dict[str, Any]]:
        """Findings contributed by a single AST node (call sink or bare except)."""
        if isinstance(node, ast.Call):
            if id(node) in nested_compiles:
                return []
            return self._check_call(rel_path, node, source, assignments)
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            return [_bare_except_finding(rel_path, node)]
        return []

    def _scan_ast(self, rel_path: str, source: str) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, MemoryError):
            return []

        nested_compiles = self._nested_compile_ids(tree)
        assignments = self._collect_assignments(tree)
        findings: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            findings.extend(self._scan_node(rel_path, source, node, nested_compiles, assignments))
        return self._drop_suppressed(findings, source)

    def _drop_suppressed(self, findings: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
        """Remove findings whose source line carries a security-suppression comment."""
        lines = source.splitlines()
        kept: list[dict[str, Any]] = []
        for f in findings:
            line_no = f.get("line", 0)
            text = lines[line_no - 1] if 1 <= line_no <= len(lines) else ""
            if not _line_suppresses(text, str(f.get("risk_type", ""))):
                kept.append(f)
        return kept

    def _check_call(
        self,
        rel_path: str,
        node: ast.Call,
        source: str,
        assignments: dict[str, list[tuple[int, ast.expr]]] | None = None,
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        func_name = self._get_call_name(node)
        if not func_name:
            return findings

        for pattern, (risk_type, severity, suggestion) in self.patterns.items():
            if not _call_pattern_matches(func_name, pattern):
                continue
            if _call_is_false_positive(pattern, func_name, node):
                continue
            findings.append(_sink_finding(rel_path, node, pattern, risk_type, severity, suggestion))

        findings.extend(_sql_injection_findings(rel_path, node, func_name, assignments))
        return findings

    def _docstring_interior_lines(self, source: str) -> set[int]:
        """Line numbers that fall *inside* a multiline string (e.g. a docstring).

        A line that is a continuation of a triple-quoted string is documentation
        or sample text, not executable code — a `SECRET_KEY = '...'` shown in a
        docstring example (common in Flask/config docs) must not be flagged as a
        real hardcoded secret. A genuine one-line assignment's value string has
        ``lineno == end_lineno`` and is never in this set.
        """
        interior: set[int] = set()
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, MemoryError):
            return interior
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                end = getattr(node, "end_lineno", node.lineno) or node.lineno
                if end > node.lineno:
                    interior.update(range(node.lineno + 1, end + 1))
        return interior

    def _scan_regex(self, rel_path: str, source: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        lines = source.splitlines()
        docstring_lines = self._docstring_interior_lines(source)
        for line_no, line in enumerate(lines, 1):
            if line_no in docstring_lines:
                continue
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
        return self._drop_suppressed(findings, source)

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
