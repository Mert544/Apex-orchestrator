"""Track-record panel in the HTML dashboard.

Apex surfaces its PROVEN track record on *this* project: the count of
test-verified, auto-rollback-guarded fixes it has landed (from
``.apex/proof-of-fix.json``) and the per-fix-type landing rates it has learned
(from ``.apex/idea-memory.json`` via ``IdeaMemory.load(root).summary()``). These
tests drive the pure render helpers directly and guard the key invariants:
gated absence (no track record → no section), deterministic content, and HTML
escaping (an XSS-laden fix key is neutralised). Pattern-matched on
tests/test_dashboard_more_edges.py and test_dashboard_anchors.py — fast,
offline, no time/random assertions.
"""

import json

from app.reporting import dashboard as D


def _write_memory(tmp_path, by_operator):
    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    (apex / "idea-memory.json").write_text(
        json.dumps({"by_operator": by_operator, "by_label": {}, "by_sequence": {}}),
        encoding="utf-8",
    )


def _write_proof(tmp_path, applied):
    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"totals": {"applied": applied}, "fixes": []}),
        encoding="utf-8",
    )


def _summary(tmp_path):
    from app.engine.idea_memory import IdeaMemory

    return IdeaMemory.load(str(tmp_path)).summary()


# --- gated absence: byte-identical to "no section" --------------------------

def test_trackrecord_absent_when_no_memory_and_no_proof(tmp_path):
    # No idea-memory.json and no proof-of-fix.json -> section is "".
    assert D._trackrecord_section(None, str(tmp_path)) == ""


def test_trackrecord_absent_with_empty_learned_and_no_proof(tmp_path):
    learned = {"most_reliable": [], "least_reliable": []}
    assert D._trackrecord_section(learned, str(tmp_path)) == ""


def test_proof_applied_count_missing_is_zero(tmp_path):
    assert D._proof_applied_count(str(tmp_path)) == 0


def test_proof_applied_count_corrupt_is_zero(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("{not json", encoding="utf-8")
    assert D._proof_applied_count(str(tmp_path)) == 0


def test_proof_applied_count_reads_totals(tmp_path):
    _write_proof(tmp_path, 7)
    assert D._proof_applied_count(str(tmp_path)) == 7


# --- renders landing rates + verified-fix count -----------------------------

def test_trackrecord_renders_rates_and_count(tmp_path):
    _write_memory(tmp_path, {
        "harden": {"applied": 8, "rolled_back": 1, "blocked": 1},
        "modernize": {"applied": 2, "rolled_back": 6, "blocked": 2},
    })
    _write_proof(tmp_path, 10)
    html_doc = D._trackrecord_section(_summary(tmp_path), str(tmp_path))
    assert "Track record" in html_doc
    # verified fix count chip
    assert "verified fixes landed" in html_doc
    assert ">10<" in html_doc
    # per-fix-type landing rates
    assert "harden" in html_doc and "80%" in html_doc
    assert "modernize" in html_doc and "20%" in html_doc


def test_trackrecord_renders_with_proof_only(tmp_path):
    # Landed fixes but no learned rates yet -> still shows the count panel.
    _write_proof(tmp_path, 3)
    html_doc = D._trackrecord_section({"most_reliable": [], "least_reliable": []},
                                      str(tmp_path))
    assert "Track record" in html_doc
    assert ">3<" in html_doc
    # No rate rows / table when nothing learned.
    assert "<table>" not in html_doc


def test_trackrecord_renders_with_memory_only(tmp_path):
    # Learned rates but no proof file -> count is 0, rates still render.
    _write_memory(tmp_path, {"harden": {"applied": 4, "rolled_back": 1, "blocked": 0}})
    html_doc = D._trackrecord_section(_summary(tmp_path), str(tmp_path))
    assert "harden" in html_doc and "80%" in html_doc


# --- sort order: success_rate desc, then key --------------------------------

def test_trackrecord_sorts_by_rate_desc_then_key(tmp_path):
    # alpha & beta tie at 50%; gamma higher. Order: gamma, alpha, beta.
    _write_memory(tmp_path, {
        "beta": {"applied": 1, "rolled_back": 1, "blocked": 0},
        "alpha": {"applied": 1, "rolled_back": 1, "blocked": 0},
        "gamma": {"applied": 3, "rolled_back": 1, "blocked": 0},
    })
    html_doc = D._trackrecord_section(_summary(tmp_path), str(tmp_path))
    assert html_doc.index("gamma") < html_doc.index("alpha") < html_doc.index("beta")


# --- de-dup across most/least lists -----------------------------------------

def test_trackrecord_dedups_key_across_lists(tmp_path):
    # A single tracked operator appears in BOTH most_reliable and least_reliable;
    # it must render exactly once.
    _write_memory(tmp_path, {"harden": {"applied": 3, "rolled_back": 1, "blocked": 0}})
    summary = _summary(tmp_path)
    assert summary["most_reliable"] and summary["least_reliable"]
    html_doc = D._trackrecord_section(summary, str(tmp_path))
    assert html_doc.count("<code>harden</code>") == 1


# --- HTML escaping / XSS ----------------------------------------------------

def test_trackrecord_escapes_xss_in_fix_key(tmp_path):
    _write_memory(tmp_path, {
        "<script>alert(1)</script>": {"applied": 2, "rolled_back": 0, "blocked": 0},
    })
    html_doc = D._trackrecord_section(_summary(tmp_path), str(tmp_path))
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc


# --- determinism ------------------------------------------------------------

def test_trackrecord_is_deterministic(tmp_path):
    _write_memory(tmp_path, {
        "harden": {"applied": 8, "rolled_back": 2, "blocked": 0},
        "modernize": {"applied": 2, "rolled_back": 8, "blocked": 0},
    })
    _write_proof(tmp_path, 10)
    summary = _summary(tmp_path)
    a = D._trackrecord_section(summary, str(tmp_path))
    b = D._trackrecord_section(summary, str(tmp_path))
    assert a == b
    # No timestamp leaked into the panel.
    assert "UTC" not in a


# --- full-page integration: gated nav + byte-identical legacy ---------------

def test_full_dashboard_includes_trackrecord_when_present(tmp_path):
    from app.reporting.dashboard import build_dashboard

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")
    _write_memory(tmp_path, {"harden": {"applied": 5, "rolled_back": 1, "blocked": 0}})
    _write_proof(tmp_path, 5)
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2, quality=False)
    assert "#trackrecord" in html_doc
    assert "Track record" in html_doc
    assert "verified fixes landed" in html_doc


def test_no_trackrecord_section_without_data(tmp_path):
    # With no idea-memory and no proof-of-fix, the gated track-record section is
    # empty and contributes no panel or nav anchor. Asserted directly rather than
    # by double-building and byte-comparing the page — the page carries a
    # minute-grained "generated HH:MM" stamp, so two builds straddling a minute
    # boundary would differ spuriously (a timing flake, not a real difference).
    from app.reporting.dashboard import build_dashboard

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")

    html = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2, quality=False)
    assert "#trackrecord" not in html
    assert "Track record" not in html
