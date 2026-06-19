"""Red-team gap closures for ``app.engine.polyglot_findings``.

Two families of fixes are pinned here:

1. SECRETS — prefixed YAML keys (``jwt_secret`` / ``POSTGRES_PASSWORD``),
   docker-compose ``password:``, URL-embedded credentials, and Dockerfile
   ``ENV``/``ARG`` credential bakes now flag; the clean counter-form of each
   (plain ``name:``, ``ENV PATH=...``, an env-ref password) does NOT.
2. XSS PRECISION — a provably-safe ``{{ "literal" | safe }}`` and a ``| safe``
   inside an HTML comment no longer fire, while a real ``{{ user | safe }}`` and
   the script/attribute-context form still do.

Every assertion keeps the module moat: the vuln fires AND its clean sibling does
not. Determinism and the minified-line bound are re-checked for the new rules.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.polyglot_findings import scan_polyglot_findings


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _by_kind(findings: list[dict], kind: str) -> list[dict]:
    return [f for f in findings if f["kind"] == kind]


# --- prefixed YAML secret keys ---------------------------------------------

def test_yaml_prefixed_secret_keys_fire(tmp_path):
    _write(
        tmp_path,
        "c.yaml",
        "jwt_secret: hunter2secret\n"
        "POSTGRES_PASSWORD: superSecretValue\n"
        "db-api-key: live_abcdef123456\n",
    )
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert sorted(h["line"] for h in hits) == [1, 2, 3]
    assert all(h["severity"] == "high" for h in hits)


def test_yaml_plain_name_key_does_not_fire(tmp_path):
    _write(tmp_path, "c.yaml", "name: app\nimage: nginx:latest\nreplicas: 3\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


def test_yaml_prefixed_secret_placeholder_clean(tmp_path):
    _write(
        tmp_path,
        "c.yml",
        "jwt_secret: ${JWT_SECRET}\nPOSTGRES_PASSWORD: changeme\n",
    )
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret") == []


def test_compose_password_block_fires(tmp_path):
    _write(
        tmp_path,
        "docker-compose.yml",
        "services:\n"
        "  db:\n"
        "    environment:\n"
        "      POSTGRES_PASSWORD: prodSecretPass1\n",
    )
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "hardcoded-secret")
    assert len(hits) == 1
    assert hits[0]["line"] == 4


# --- URL-embedded credentials ----------------------------------------------

def test_yaml_url_credential_fires(tmp_path):
    _write(
        tmp_path,
        "c.yaml",
        "dsn: postgres://admin:s3cretP@db.example.com:5432/app\n"
        "url: https://api.example.com/v1/health\n",
    )
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential")
    assert len(hits) == 1
    assert hits[0]["line"] == 1
    assert hits[0]["severity"] == "high"


def test_yaml_url_no_credential_clean(tmp_path):
    _write(tmp_path, "c.yaml", "url: https://user@host/path\nrepo: git://host/r.git\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential") == []


def test_yaml_url_envref_password_clean(tmp_path):
    _write(tmp_path, "c.yaml", "dsn: postgres://admin:${DB_PASS}@host/app\n")
    assert _by_kind(scan_polyglot_findings(str(tmp_path)), "url-credential") == []


# --- Dockerfile -------------------------------------------------------------

def test_dockerfile_env_secret_fires(tmp_path):
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


def test_dockerfile_env_path_clean(tmp_path):
    _write(
        tmp_path,
        "Dockerfile",
        "ENV PATH=/usr/bin\nENV PYTHONPATH=/app\nENV LANG=C.UTF-8\n",
    )
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


# --- XSS precision: literal | safe -----------------------------------------

def test_jinja_literal_safe_does_not_fire(tmp_path):
    _write(
        tmp_path,
        "p.html",
        '<p>{{ "literal text" | safe }}</p>\n'
        "<p>{{ 'another literal' | safe }}</p>\n",
    )
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe") == []
    assert _by_kind(findings, "jinja-safe-context") == []


def test_jinja_user_safe_still_fires(tmp_path):
    _write(tmp_path, "p.html", "<p>{{ user.bio | safe }}</p>\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-safe")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


def test_jinja_mixed_literal_and_user_fires(tmp_path):
    _write(tmp_path, "p.html", '<p>{{ "ok" | safe }} {{ user | safe }}</p>\n')
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-safe")
    assert len(hits) == 1
    assert hits[0]["line"] == 1


# --- XSS precision: | safe inside an HTML comment ---------------------------

def test_jinja_safe_in_comment_does_not_fire(tmp_path):
    _write(tmp_path, "p.html", "<!-- {{ user | safe }} legacy -->\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe") == []
    assert _by_kind(findings, "jinja-safe-context") == []


def test_jinja_safe_after_closed_comment_still_fires(tmp_path):
    _write(tmp_path, "p.html", "<!-- note --> {{ user | safe }}\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-safe")
    assert len(hits) == 1


def test_jinja_literal_safe_in_script_context_clean(tmp_path):
    _write(tmp_path, "p.html", '<script>var x = {{ "literal" | safe }};</script>\n')
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe-context") == []
    assert _by_kind(findings, "jinja-safe") == []


def test_jinja_user_safe_in_script_context_fires(tmp_path):
    _write(tmp_path, "p.html", "<script>var x = {{ user | safe }};</script>\n")
    hits = _by_kind(scan_polyglot_findings(str(tmp_path)), "jinja-safe-context")
    assert len(hits) == 1


# --- determinism / bounds for the new rules --------------------------------

def test_new_rules_deterministic(tmp_path):
    _write(tmp_path, "c.yaml", "jwt_secret: hunter2secret\n")
    _write(tmp_path, "Dockerfile", "ENV API_KEY=sk-live-abcdef123456\n")
    _write(tmp_path, "p.html", "<p>{{ user | safe }}</p>\n")
    first = scan_polyglot_findings(str(tmp_path))
    second = scan_polyglot_findings(str(tmp_path))
    assert first == second
    keys = [(f["path"], f["line"], f["kind"]) for f in first]
    assert keys == sorted(keys)


def test_minified_long_line_no_crash(tmp_path):
    huge = "x" * 200_000 + "{{ user | safe }}"
    _write(tmp_path, "p.html", huge + "\n")
    _write(tmp_path, "Dockerfile", "ENV API_KEY=" + "a" * 200_000 + "\n")
    # No crash; the oversized lines are skipped by the _MAX_LINE_LEN bound.
    findings = scan_polyglot_findings(str(tmp_path))
    assert _by_kind(findings, "jinja-safe") == []
    assert _by_kind(findings, "hardcoded-secret") == []
