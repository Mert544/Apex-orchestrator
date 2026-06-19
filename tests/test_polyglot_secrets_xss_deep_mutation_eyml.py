"""Deep-mutation hardening for polyglot secret / XSS detection.

Targets the Batch-2 work in ``app/engine/polyglot_findings.py``:

  * prefixed / URL / Dockerfile SECRET detectors — ``jwt_secret:`` /
    ``POSTGRES_PASSWORD:`` / a URL-embedded credential / Dockerfile
    ``ENV NAME=secret`` flag; ``name: app`` / ``ENV PATH=...`` / a CI
    ``${{ secrets.X }}`` expression / an env-ref password do NOT;
  * the XSS literal/comment FALSE-POSITIVE fixes (``_real_jinja_safe`` /
    ``_in_html_comment`` / the literal-suppression regex): ``{{ "literal" | safe }}``
    and a ``| safe`` inside a comment do NOT flag, while ``{{ user | safe }}`` and
    ``autoescape false`` STILL do.

Each shape pins an EXACT kind / severity / line / count so a flipped guard or a
relaxed regex fails a test. Deep-mutation companion to
``test_polyglot_secrets_xss_eyml.py``.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.polyglot_findings import (
    scan_polyglot_findings,
    _is_placeholder,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _by_kind(findings: list[dict], kind: str) -> list[dict]:
    return [f for f in findings if f["kind"] == kind]


# --- _is_placeholder unit pins ----------------------------------------------

def test_is_placeholder_short_value_true():
    # Values shorter than 6 chars are treated as placeholders (conservative).
    assert _is_placeholder("abc") is True
    assert _is_placeholder("12345") is True


def test_is_placeholder_real_secret_false():
    assert _is_placeholder("hunter2secret") is False


def test_is_placeholder_env_ref_true():
    assert _is_placeholder("${JWT_SECRET}") is True
    assert _is_placeholder("$VAULT") is True


def test_is_placeholder_ci_expression_true():
    assert _is_placeholder("${{ secrets.API_KEY }}") is True


def test_is_placeholder_strips_trailing_comment():
    # A value with a trailing YAML comment: the real value before " #" decides.
    assert _is_placeholder("changeme  # fixme") is True
    assert _is_placeholder("realLongSecret  # used by db") is False


def test_is_placeholder_sentinels_true():
    for v in ("changeme", "placeholder", "example", "your_token_here", "xxxxxx", "todo"):
        assert _is_placeholder(v) is True, v


# --- prefixed YAML secret keys ----------------------------------------------

def test_yaml_jwt_secret_fires_exact(tmp_path):
    _write(tmp_path, "c.yaml", "jwt_secret: hunter2secret\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "high"


def test_yaml_postgres_password_fires(tmp_path):
    _write(tmp_path, "c.yaml", "POSTGRES_PASSWORD: superSecretValue\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1


def test_yaml_bare_password_key_fires(tmp_path):
    # The prefix is optional — the bare credential key still matches.
    _write(tmp_path, "c.yaml", "password: prodSecretPass1\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1


def test_yaml_plain_name_key_does_not_fire(tmp_path):
    _write(tmp_path, "c.yaml", "name: app\nimage: nginx:latest\nreplicas: 3\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


def test_yaml_prefixed_secret_envref_clean(tmp_path):
    _write(tmp_path, "c.yml", "jwt_secret: ${JWT_SECRET}\nPOSTGRES_PASSWORD: changeme\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


def test_yaml_secret_ci_expression_clean(tmp_path):
    # A GitHub Actions ${{ secrets.X }} reference is NOT a literal secret.
    _write(tmp_path, "c.yaml", "api_key: ${{ secrets.API_KEY }}\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


# --- URL-embedded credentials -----------------------------------------------

def test_yaml_url_credential_fires_exact(tmp_path):
    _write(
        tmp_path, "c.yaml",
        "dsn: postgres://admin:s3cretP@db.example.com:5432/app\n"
        "url: https://api.example.com/v1/health\n",
    )
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "high"


def test_url_no_credential_clean(tmp_path):
    # https://host/path and a single-component user@host (no :pass@) do not match.
    _write(tmp_path, "c.yaml", "url: https://user@host/path\nrepo: git://host/r.git\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential") == []


def test_url_envref_password_clean(tmp_path):
    _write(tmp_path, "c.yaml", "dsn: postgres://admin:${DB_PASS}@host/app\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential") == []


def test_url_literal_password_word_clean(tmp_path):
    # A literal "password"/"pass"/"user" placeholder secret in the URL is excluded.
    _write(tmp_path, "c.yaml", "dsn: postgres://admin:password@host/app\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential") == []


# --- Dockerfile secrets ------------------------------------------------------

def test_dockerfile_env_secret_fires_exact(tmp_path):
    _write(tmp_path, "Dockerfile", "FROM python\nENV API_KEY=sk-live-abcdef123456\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["line"] == 2
    assert hits[0]["severity"] == "high"


def test_dockerfile_arg_secret_fires(tmp_path):
    _write(tmp_path, "api.dockerfile", "ARG DB_PASSWORD=prodSecretPass1\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_dockerfile_legacy_space_form_fires(tmp_path):
    # The legacy "ENV NAME value" (space) form is also recognized.
    _write(tmp_path, "Dockerfile", "ENV API_KEY sk-live-abcdef123456\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1


def test_dockerfile_env_path_clean(tmp_path):
    _write(tmp_path, "Dockerfile", "ENV PATH=/usr/bin\nENV PYTHONPATH=/app\nENV LANG=C.UTF-8\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


def test_dockerfile_env_envref_clean(tmp_path):
    _write(tmp_path, "Dockerfile", "ARG TOKEN=${CI_TOKEN}\nENV SECRET=$VAULT\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


def test_dockerfile_named_variant_in_scope(tmp_path):
    _write(tmp_path, "Dockerfile.prod", "ENV PASSWORD=hunter2secret\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["path"] == "Dockerfile.prod"


def test_dockerfile_url_credential_fires(tmp_path):
    _write(tmp_path, "Dockerfile", "RUN pip install https://u:p4ssword@host/pkg\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential")
    assert len(hits) == 1


# --- XSS precision: literal | safe is suppressed, user | safe still fires ----

def test_jinja_literal_safe_does_not_fire(tmp_path):
    _write(
        tmp_path, "p.html",
        '<p>{{ "literal text" | safe }}</p>\n'
        "<p>{{ 'another literal' | safe }}</p>\n",
    )
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe") == []
    assert _by_kind(findings, "jinja-safe-context") == []


def test_jinja_user_safe_fires_exact(tmp_path):
    _write(tmp_path, "p.html", "<p>{{ user.bio | safe }}</p>\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-safe")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "high"


def test_jinja_mixed_literal_and_user_fires_once(tmp_path):
    # _real_jinja_safe returns True as soon as one occurrence is a real sink.
    _write(tmp_path, "p.html", '<p>{{ "ok" | safe }} {{ user | safe }}</p>\n')
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-safe")
    assert len(hits) == 1


def test_jinja_plain_interpolation_no_safe_clean(tmp_path):
    # Auto-escaped {{ x }} (no | safe) is never a finding.
    _write(tmp_path, "p.html", "<p>{{ user.name }}</p>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe") == []
    assert _by_kind(findings, "jinja-safe-context") == []


# --- XSS precision: | safe inside an HTML comment ---------------------------

def test_jinja_safe_in_comment_does_not_fire(tmp_path):
    _write(tmp_path, "p.html", "<!-- {{ user | safe }} legacy -->\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe") == []
    assert _by_kind(findings, "jinja-safe-context") == []


def test_jinja_safe_after_closed_comment_still_fires(tmp_path):
    # The comment closes BEFORE the | safe, so it is live code again.
    _write(tmp_path, "p.html", "<!-- note --> {{ user | safe }}\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-safe")
    assert len(hits) == 1


# --- XSS: autoescape false still fires, autoescape true does not -------------

def test_autoescape_false_fires_exact(tmp_path):
    _write(tmp_path, "p.html", "{% autoescape false %}\n{{ user }}\n{% endautoescape %}\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-autoescape-off")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "high"


def test_autoescape_true_does_not_fire(tmp_path):
    _write(tmp_path, "p.html", "{% autoescape true %}\n{{ user }}\n{% endautoescape %}\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-autoescape-off") == []


# --- XSS: script/attribute context yields the stronger signal ---------------

def test_jinja_user_safe_in_script_context_fires_context_kind(tmp_path):
    _write(tmp_path, "p.html", "<script>var x = {{ user | safe }};</script>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    ctx = _by_kind(findings, "jinja-safe-context")
    assert len(ctx) == 1
    assert ctx[0]["severity"] == "high"
    # The stronger context signal SUPPRESSES the plain jinja-safe (elif branch).
    assert _by_kind(findings, "jinja-safe") == []


def test_jinja_literal_safe_in_script_context_clean(tmp_path):
    _write(tmp_path, "p.html", '<script>var x = {{ "literal" | safe }};</script>\n')
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe-context") == []
    assert _by_kind(findings, "jinja-safe") == []


# --- determinism / bounds for the new rules ---------------------------------

def test_new_rules_deterministic_and_sorted(tmp_path):
    _write(tmp_path, "c.yaml", "jwt_secret: hunter2secret\n")
    _write(tmp_path, "Dockerfile", "ENV API_KEY=sk-live-abcdef123456\n")
    _write(tmp_path, "p.html", "<p>{{ user | safe }}</p>\n")
    first = scan_polyglot_findings(str(tmp_path))
    second = scan_polyglot_findings(str(tmp_path))
    assert first == second
    keys = [(f["path"], f["line"], f["kind"]) for f in first]
    assert keys == sorted(keys)


def test_minified_long_line_skipped_no_crash(tmp_path):
    huge = "x" * 200_000 + "{{ user | safe }}"
    _write(tmp_path, "p.html", huge + "\n")
    _write(tmp_path, "Dockerfile", "ENV API_KEY=" + "a" * 200_000 + "\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe") == []
    assert _by_kind(findings, "hardcoded-secret") == []
