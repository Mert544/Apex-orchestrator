"""Deterministic, high-confidence security/quality FINDINGS over NON-Python source.

Apex deep-analyses Python, but the projects it develops are polyglot — the
TypeScript / JavaScript / YAML / HTML / shell remainder is structurally outside
the Python AST scope, so Apex is blind to risk that lives there. ``app.engine.
polyglot_metrics`` already reports the *shape* of that remainder (size, nesting,
debt) from cheap text heuristics; this module is the complementary ISSUES view:
a CURATED set of high-confidence, recommend-only line detectors.

The moat here is "never a false alarm". Apex must not cry wolf on another
language it can't truly parse, so every detector keys off an explicit, narrow,
unambiguous pattern and we prefer NOT firing over a false positive. Where a cheap
guard removes an obvious string/comment false positive we apply it; where a guard
would be expensive or fragile we simply keep the pattern tight enough that the
clean counter-form does not match. Each detector ships with a clean counter-form
exercised in the tests, so "the safe code does not fire" is a tested invariant.

Detectors (pattern -> why it is near-zero-false-positive):

  JS/TS
    - ``eval(`` / ``new Function(``  — a real dynamic-code call; the word-boundary
      anchor means ``myeval(`` / ``evaluate(`` do not match.
    - ``child_process`` ``.exec(`` with a string/template arg — shell-out with a
      literal or interpolated command; ``.execFile(`` (the safe arg-array form)
      does not match.
    - ``.innerHTML =`` assignment — an XSS sink; ``.textContent =`` and reads of
      ``.innerHTML`` (no ``=``) do not match.
    - a hardcoded secret literal assigned to a ``password|secret|apikey|token``
      identifier — the value must be a non-trivial, non-placeholder string.
    - ``rejectUnauthorized: false`` / ``verify: false`` — TLS verification off.

  YAML
    - a secret-looking key (``password:`` / ``api_key:`` / ``token:`` / ``secret:``)
      with a non-placeholder literal value.
    - ``verify_ssl: false`` / ``insecure: true`` — verification disabled.
    - a ``curl ... | sh`` / ``wget ... | sh`` pipe-to-shell line (e.g. in a CI run
      step).

  Shell (.sh)
    - ``curl ... | sh`` / pipe-to-shell.
    - ``eval`` of a variable — ``eval "$cmd"`` / ``eval $cmd``.
    - ``rm -rf $`` — a recursive force-delete rooted at an UNQUOTED variable
      (the classic ``rm -rf $DIR/`` foot-gun); ``rm -rf /tmp/build`` (a literal
      path) does not match.
    - a hardcoded secret assignment (``PASSWORD=...`` etc.).

  HTML
    - an inline ``javascript:`` URL (``href="javascript:..."``).
    - an ``on*=`` event handler whose body calls ``eval(``.

Determinism: fixed compiled patterns, no time/random; results sorted by
``(path, line, kind)`` and bounded by ``max_files``. Best-effort and total:
unreadable files are skipped, no in-scope source yields ``[]``, nothing raises.

Recommend-only, stdlib + regex only, offline, no LLM. Reuses the canonical
``app.engine.skip_dirs.is_skipped`` predicate as the ONLY skip set.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.engine.skip_dirs import is_skipped

__all__ = ["scan_polyglot_findings"]

# In-scope extensions grouped by detector family. ``.suffix.lower()`` is matched.
_JS_EXTS = frozenset({".ts", ".tsx", ".js", ".jsx"})
_YAML_EXTS = frozenset({".yaml", ".yml"})
_HTML_EXTS = frozenset({".html"})
_SHELL_EXTS = frozenset({".sh"})

# A line longer than this is treated as minified/generated and skipped — such
# lines defeat the "unambiguous pattern" guarantee. Fixed, deterministic.
_MAX_LINE_LEN = 2000

# Secret-bearing identifier stems (JS/shell/YAML keys). Word-boundary matched so
# ``password`` matches but ``passwordHash`` is allowed to match too (still a
# secret-shaped name) while ``compass`` does not.
_CRED_FIELD = r"(?:password|passwd|secret|apikey|api_key|token|access_key|private_key)"

# A placeholder value we must NOT flag: env refs, templates, empty, and the
# obvious "fill me in" sentinels. Lowercased value is tested against this.
_PLACEHOLDER_RE = re.compile(
    r"""^(?:
        |""|''                              # empty literal
        |\$\{?[a-z_].*                       # ${VAR} / $VAR interpolation
        |\{\{.*\}\}                          # {{ template }}
        |<.*>                                # <your-token-here>
        |process\.env\..*                    # process.env.X
        |.*\b(?:changeme|placeholder|example|your[_-]?\w*|xxx+|todo|null|none|undefined)\b.*
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

# --- JS/TS -----------------------------------------------------------------
# eval( / new Function( as a real call. \b before eval rejects ``myeval(`` and
# ``.eval`` member access is rejected by requiring a non-dot before ``eval``.
_JS_EVAL_RE = re.compile(r"(?<![.\w])eval\s*\(|new\s+Function\s*\(")
# child_process exec with a string/template arg (not execFile's array form).
_JS_EXEC_RE = re.compile(r"\.exec(?:Sync)?\s*\(\s*[`'\"$]")
# innerHTML assignment (the XSS write sink); requires ``=`` not ``==``/read.
_JS_INNERHTML_RE = re.compile(r"\.innerHTML\s*=(?!=)")
# secret literal assigned to a secret-named identifier.
_JS_SECRET_RE = re.compile(
    rf"""\b{_CRED_FIELD}\b\s*[:=]\s*(['"`])(?P<val>[^'"`]*)\1""",
    re.IGNORECASE,
)
# TLS verification disabled.
_JS_TLS_RE = re.compile(r"\b(?:rejectUnauthorized|verify)\s*:\s*false\b")

# --- YAML ------------------------------------------------------------------
# secret-looking key with a literal scalar value (quoted or bare).
_YAML_SECRET_RE = re.compile(
    rf"""^\s*['"]?{_CRED_FIELD}['"]?\s*:\s*(?P<val>\S.*?)\s*$""",
    re.IGNORECASE,
)
# verify_ssl: false / insecure: true.
_YAML_TLS_RE = re.compile(
    r"^\s*(?:verify_ssl|ssl_verify|sslverify)\s*:\s*false\b"
    r"|^\s*insecure\s*:\s*true\b",
    re.IGNORECASE,
)

# --- pipe-to-shell (YAML run-steps and shell) ------------------------------
_PIPE_SHELL_RE = re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b")

# --- Shell -----------------------------------------------------------------
# eval of a variable: ``eval "$x"`` / ``eval $x``.
_SH_EVAL_RE = re.compile(r"(?<![\w.])eval\s+[\"']?\$")
# rm -rf rooted at an unquoted variable (the dangerous, expandable form).
_SH_RMRF_RE = re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+\$|\brm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+\$")
# secret assignment: NAME=<literal>. Bare or quoted value, no $ interpolation.
_SH_SECRET_RE = re.compile(
    rf"""^\s*(?:export\s+)?{_CRED_FIELD}\s*=\s*(?P<val>['"]?[^$\s'"][^'"]*)['"]?\s*$""",
    re.IGNORECASE,
)

# --- HTML ------------------------------------------------------------------
# inline javascript: URL in an href/src attribute.
_HTML_JSURL_RE = re.compile(r"""\b(?:href|src|action)\s*=\s*["']?\s*javascript:""", re.IGNORECASE)
# on*= handler that calls eval(.
_HTML_ONEVAL_RE = re.compile(r"""\bon\w+\s*=\s*["'][^"']*\beval\s*\(""", re.IGNORECASE)


def _ext_family(name: str) -> str | None:
    """Detector family for a basename suffix, or ``None`` if out of scope. Pure."""
    suffix = Path(name).suffix.lower()
    if suffix in _JS_EXTS:
        return "js"
    if suffix in _YAML_EXTS:
        return "yaml"
    if suffix in _HTML_EXTS:
        return "html"
    if suffix in _SHELL_EXTS:
        return "shell"
    return None


def _is_placeholder(value: str) -> bool:
    """True if a captured secret VALUE is a placeholder we must not flag. Pure.

    Strips surrounding quotes, then rejects empty / very short values and any
    env-ref / template / sentinel value. Conservative: when in doubt (e.g. the
    value is short) we treat it as a placeholder so we do NOT fire.
    """
    val = value.strip().strip("'\"`").strip()
    if len(val) < 6:
        return True
    return bool(_PLACEHOLDER_RE.match(val))


def _secret_finding(line: str, regex: re.Pattern[str], kind: str) -> tuple[str, str, str] | None:
    """A ``(severity, kind, message)`` secret finding, or ``None`` if a placeholder.

    Shared by the JS / YAML / shell secret detectors: matches ``regex``, extracts
    its ``val`` group, and only fires when the value is a real (non-placeholder)
    literal. Pure.
    """
    match = regex.search(line)
    if not match:
        return None
    if _is_placeholder(match.group("val")):
        return None
    return ("high", kind, "Hardcoded secret literal assigned to a credential-named field")


def _scan_js(line: str) -> list[tuple[str, str, str]]:
    """JS/TS detectors for one line as ``(severity, kind, message)`` tuples. Pure."""
    out: list[tuple[str, str, str]] = []
    if _JS_EVAL_RE.search(line):
        out.append(("high", "js-eval", "Dynamic code execution via eval/new Function"))
    if _JS_EXEC_RE.search(line):
        out.append(("high", "js-exec", "Shell command executed from a string/template (command-injection risk)"))
    if _JS_INNERHTML_RE.search(line):
        out.append(("medium", "js-innerhtml", "Assignment to innerHTML is an XSS sink"))
    if _JS_TLS_RE.search(line):
        out.append(("high", "tls-verify-off", "TLS certificate verification disabled"))
    secret = _secret_finding(line, _JS_SECRET_RE, "hardcoded-secret")
    if secret:
        out.append(secret)
    return out


def _scan_yaml(line: str) -> list[tuple[str, str, str]]:
    """YAML detectors for one line as ``(severity, kind, message)`` tuples. Pure."""
    out: list[tuple[str, str, str]] = []
    if _YAML_TLS_RE.search(line):
        out.append(("high", "tls-verify-off", "SSL/TLS verification disabled"))
    if _PIPE_SHELL_RE.search(line):
        out.append(("high", "pipe-to-shell", "Remote script piped directly into a shell"))
    secret = _secret_finding(line, _YAML_SECRET_RE, "hardcoded-secret")
    if secret:
        out.append(secret)
    return out


def _scan_shell(line: str) -> list[tuple[str, str, str]]:
    """Shell detectors for one line as ``(severity, kind, message)`` tuples. Pure."""
    out: list[tuple[str, str, str]] = []
    if _PIPE_SHELL_RE.search(line):
        out.append(("high", "pipe-to-shell", "Remote script piped directly into a shell"))
    if _SH_EVAL_RE.search(line):
        out.append(("high", "sh-eval", "eval of a variable can execute injected code"))
    if _SH_RMRF_RE.search(line):
        out.append(("high", "sh-rm-rf", "rm -rf on an unquoted variable path is destructive if empty/unset"))
    secret = _secret_finding(line, _SH_SECRET_RE, "hardcoded-secret")
    if secret:
        out.append(secret)
    return out


def _scan_html(line: str) -> list[tuple[str, str, str]]:
    """HTML detectors for one line as ``(severity, kind, message)`` tuples. Pure."""
    out: list[tuple[str, str, str]] = []
    if _HTML_JSURL_RE.search(line):
        out.append(("medium", "html-js-url", "Inline javascript: URL"))
    if _HTML_ONEVAL_RE.search(line):
        out.append(("high", "html-on-eval", "Inline event handler calls eval"))
    return out


_SCANNERS = {
    "js": _scan_js,
    "yaml": _scan_yaml,
    "shell": _scan_shell,
    "html": _scan_html,
}


def _scan_file(path: Path, rel: str, family: str) -> list[dict]:
    """Run the family's line detectors over one file. ``[]`` if unreadable. Pure read.

    The single shared per-file line scan: read the text best-effort, iterate
    physical lines (1-based), skip blank/oversized lines, and delegate to the
    family scanner. Returns one finding dict per detector hit. Never raises.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    scanner = _SCANNERS[family]
    findings: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or len(line) > _MAX_LINE_LEN:
            continue
        for severity, kind, message in scanner(line):
            findings.append({
                "path": rel, "line": lineno,
                "severity": severity, "kind": kind, "message": message,
            })
    return findings


def _iter_candidates(root_path: Path) -> list[tuple[str, str]]:
    """In-scope non-Python source files as ``(rel_posix, family)``, sorted by path.

    Walks once, keeping files whose extension is in scope and whose path crosses
    no excluded directory (``is_skipped``). Sorted so a downstream cap is
    reproducible. Pure aside from the directory walk.
    """
    found: list[tuple[str, str]] = []
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root_path)
        if is_skipped(rel):
            continue
        family = _ext_family(path.name)
        if family is None:
            continue
        found.append((rel.as_posix(), family))
    found.sort()
    return found


def scan_polyglot_findings(root: str, max_files: int = 400) -> list[dict]:
    """High-confidence security/quality findings in non-Python source under ``root``.

    Walks every in-scope ``.ts/.tsx/.js/.jsx/.yaml/.yml/.html/.sh`` file (skipping
    the canonical excluded directories via ``is_skipped``) and runs a CURATED set
    of conservative, near-zero-false-positive line detectors over it (see the
    module docstring for the full detector list and rationale). Each finding is
    ``{"path", "line", "severity", "kind", "message"}``.

    Bounded: at most ``max_files`` files (smallest paths first, since candidates
    are path-sorted before the cap) are scanned. Results are returned sorted by
    ``(path, line, kind)`` so the output is deterministic for a given repo state.

    Recommend-only and total: unreadable files are skipped; ``max_files <= 0`` or
    a missing root yields ``[]``; no in-scope source yields ``[]``. Never raises.
    """
    root_path = Path(root)
    if max_files <= 0 or not root_path.exists():
        return []
    candidates = _iter_candidates(root_path)[:max_files]
    findings: list[dict] = []
    for rel, family in candidates:
        findings.extend(_scan_file(root_path / rel, rel, family))
    findings.sort(key=lambda f: (f["path"], f["line"], f["kind"]))
    return findings
