"""Tests for ``app.engine.polyglot_findings``.

The moat is "never a false alarm", so for EVERY detector we assert two things:
the vuln line fires (right kind / severity / line), AND the clean counter-form
on a sibling line does NOT fire. Plus determinism, the ``max_files`` cap,
empty / no-source -> ``[]``, and an unreadable file tolerated.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.polyglot_findings import scan_polyglot_findings


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _kinds(findings: list[dict]) -> set[str]:
    return {f["kind"] for f in findings}


def _by_kind(findings: list[dict], kind: str) -> list[dict]:
    return [f for f in findings if f["kind"] == kind]


# --- JS/TS -----------------------------------------------------------------

def test_js_eval_fires_and_clean_does_not(tmp_path):
    _write(tmp_path, "a.js", "eval(userInput);\nmyeval(x);\nevaluate(y);\n")
    findings = scan_polyglot_findings(str(tmp_path))
    evals = _by_kind(findings, "js-eval")
    assert len(evals) == 1
    assert evals[0]["line"] == 1
    assert evals[0]["severity"] == "high"


def test_js_new_function_fires(tmp_path):
    _write(tmp_path, "a.ts", "const f = new Function('a', 'return a');\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "js-eval")


def test_js_exec_fires_and_execfile_clean(tmp_path):
    _write(tmp_path, "a.js", "cp.exec(`rm ${name}`);\ncp.execFile('ls', args);\n")
    findings = scan_polyglot_findings(str(tmp_path))
    exec_f = _by_kind(findings, "js-exec")
    assert len(exec_f) == 1
    assert exec_f[0]["line"] == 1


def test_js_innerhtml_fires_and_textcontent_clean(tmp_path):
    _write(tmp_path, "a.js", "el.innerHTML = data;\nel.textContent = data;\nif (a.innerHTML == b) {}\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "js-innerhtml")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "medium"


def test_js_secret_fires_and_env_clean(tmp_path):
    _write(tmp_path, "a.ts", 'const password = "hunter2secret";\nconst secret = process.env.SECRET;\nconst apiKey = "";\n')
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_js_secret_placeholder_clean(tmp_path):
    _write(tmp_path, "a.ts", 'const token = "changeme";\nconst secret = "<your-secret>";\n')
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


def test_js_tls_fires_and_true_clean(tmp_path):
    _write(tmp_path, "a.js", "{ rejectUnauthorized: false }\n{ rejectUnauthorized: true }\n{ verify: false }\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "tls-verify-off")
    assert sorted(h["line"] for h in hits) == [1, 3]


# --- YAML ------------------------------------------------------------------

def test_yaml_secret_fires_and_placeholder_clean(tmp_path):
    _write(tmp_path, "c.yaml", "password: SuperSecret123\napi_key: ${API_KEY}\ntoken: changeme\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_yaml_tls_fires_and_true_clean(tmp_path):
    _write(tmp_path, "c.yml", "verify_ssl: false\ninsecure: true\nverify_ssl: true\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "tls-verify-off")
    assert sorted(h["line"] for h in hits) == [1, 2]


def test_yaml_pipe_to_shell_fires_and_clean(tmp_path):
    _write(tmp_path, "c.yaml", "run: curl https://x.sh | sh\nrun: curl https://x.sh -o out\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "pipe-to-shell")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


# --- Shell -----------------------------------------------------------------

def test_shell_pipe_fires_and_clean(tmp_path):
    _write(tmp_path, "s.sh", "wget https://x.sh | sh\nwget https://x.sh -O out\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "pipe-to-shell")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_shell_eval_fires_and_clean(tmp_path):
    _write(tmp_path, "s.sh", 'eval "$cmd"\neval is a builtin worth avoiding\n')
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "sh-eval")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_shell_rmrf_fires_on_var_and_literal_clean(tmp_path):
    _write(tmp_path, "s.sh", "rm -rf $DIR/\nrm -rf /tmp/build\nrm -rf ./node_modules\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "sh-rm-rf")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_shell_secret_fires_and_env_clean(tmp_path):
    _write(tmp_path, "s.sh", "PASSWORD=hunter2secret\nexport TOKEN=$CI_TOKEN\nSECRET=${VAULT}\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


# --- HTML ------------------------------------------------------------------

def test_html_js_url_fires_and_clean(tmp_path):
    _write(tmp_path, "p.html", '<a href="javascript:alert(1)">x</a>\n<a href="https://ok">y</a>\n')
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "html-js-url")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "medium"


def test_html_on_eval_fires_and_clean(tmp_path):
    _write(tmp_path, "p.html", '<button onclick="eval(payload)">x</button>\n<button onclick="submit()">y</button>\n')
    findings = scan_polyglot_findings(str(tmp_path))
    hits = _by_kind(findings, "html-on-eval")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


# --- structural / total ----------------------------------------------------

def test_finding_shape(tmp_path):
    _write(tmp_path, "a.js", "eval(x);\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert findings
    for f in findings:
        assert set(f) == {"path", "line", "severity", "kind", "message"}
        assert isinstance(f["line"], int) and f["line"] >= 1
        assert f["severity"] in {"high", "medium", "low"}
        assert isinstance(f["message"], str) and f["message"]


def test_deterministic_and_sorted(tmp_path):
    _write(tmp_path, "z.sh", "eval $x\nrm -rf $D\n")
    _write(tmp_path, "a.js", "eval(x);\nel.innerHTML = y;\n")
    first = scan_polyglot_findings(str(tmp_path))
    second = scan_polyglot_findings(str(tmp_path))
    assert first == second
    keys = [(f["path"], f["line"], f["kind"]) for f in first]
    assert keys == sorted(keys)


def test_max_files_cap(tmp_path):
    for i in range(5):
        _write(tmp_path, f"f{i}.js", "eval(x);\n")
    assert {f["path"] for f in scan_polyglot_findings(str(tmp_path), max_files=2)} == {"f0.js", "f1.js"}
    assert scan_polyglot_findings(str(tmp_path), max_files=0) == []


def test_empty_and_no_source(tmp_path):
    assert scan_polyglot_findings(str(tmp_path)) == []
    _write(tmp_path, "readme.md", "# hi\n")
    _write(tmp_path, "code.py", "eval('x')\n")
    assert scan_polyglot_findings(str(tmp_path)) == []


def test_missing_root_returns_empty(tmp_path):
    assert scan_polyglot_findings(str(tmp_path / "nope")) == []


def test_skipped_dirs_excluded(tmp_path):
    _write(tmp_path, "node_modules/lib.js", "eval(x);\n")
    _write(tmp_path, ".claude/wt/a.js", "eval(x);\n")
    assert scan_polyglot_findings(str(tmp_path)) == []


def test_unreadable_file_tolerated(tmp_path):
    import os
    import stat

    _write(tmp_path, "good.js", "eval(x);\n")
    bad = tmp_path / "bad.js"
    bad.write_text("eval(x);\n", encoding="utf-8")
    os.chmod(bad, 0)  # remove read permission so read_text raises OSError
    try:
        findings = scan_polyglot_findings(str(tmp_path))
    finally:
        os.chmod(bad, stat.S_IRUSR | stat.S_IWUSR)
    # good.js always scanned; bad.js is skipped if truly unreadable (root may
    # bypass perms, in which case it scans cleanly) — either way, no crash.
    assert "good.js" in {f["path"] for f in findings}


def test_minified_long_line_skipped(tmp_path):
    _write(tmp_path, "min.js", "x;" * 1500 + "eval(payload);\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "js-eval") == []
