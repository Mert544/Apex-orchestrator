"""The "living manifesto" dashboard card — the architectural laws Apex has
learned on THIS project (``app.engine.manifesto``), made visible.

Mirrors the other "living-cell" cards (``_native_mind_section``,
``_memory_vault_section``): self-gates to ``""`` when there is nothing to show
(so the page stays byte-identical to before on a fresh project), otherwise
renders a ``_card`` with a chip per law-count and short lists of the top
avoid/fragile/trust/idiom laws. Wired through ``dashboard.py`` exactly like
``nativemind``: a ``manifesto_html`` field on ``RenderedSections``, a gated nav
link, and a slot in ``_page_sections``.

Fixture style mirrors ``tests/test_manifesto_eyml.py`` (fabricates
``proof-of-fix.json`` fixes + a native landing) so ``derive_manifesto`` returns
non-empty laws.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.native_proof_memory import record_native_landing
from app.engine.proof_of_fix import SCHEMA
from app.reporting import dashboard as d
from app.reporting.dashboard_sections import RenderedSections, _manifesto_section


def _proof(root: Path, fixes: list[dict]) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"schema": SCHEMA, "generated_at": "2026-01-01", "fixes": fixes}),
        encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"outcome": outcome,
            "finding": {"action": action, "target": module},
            "changed_files": [module]}


def _learned_project(tmp_path: Path) -> Path:
    _proof(tmp_path, [
        *[_fix("risky-x", "app/bad.py", "rolled_back") for _ in range(4)],
        _fix("risky-x", "app/bad.py", "applied"),
        *[_fix("safe-y", "app/good.py", "applied") for _ in range(6)],
    ])
    record_native_landing(tmp_path, ["2:p0 + p1"])
    return tmp_path


def _small_python_project(tmp: Path) -> Path:
    """A minimal real source tree so ``build_dashboard``'s profiler has
    something to analyze (mirrors ``tests/test_dashboard_render_helpers.py``)."""
    (tmp / "app").mkdir(exist_ok=True)
    (tmp / "app" / "svc.py").write_text("def run(cmd):\n    return cmd\n", encoding="utf-8")
    return tmp


# --- Card renderer: self-gating, content, determinism -----------------------

def test_manifesto_card_renders_with_laws(tmp_path):
    _learned_project(tmp_path)
    html = _manifesto_section(str(tmp_path))
    assert "Living manifesto — architectural laws learned here" in html
    assert "id='manifesto'" in html
    assert "avoid" in html and "fragile" in html and "trust" in html
    assert "app/bad.py" in html  # the fragile module surfaces
    assert "risky-x" in html  # the avoided action surfaces
    # The proven idiom is HUMANISED via manifesto._shape_label — the same
    # rendering the vault/CLI markdown uses — never the raw internal arity key.
    assert "p0 + p1 (2-arg)" in html
    assert "2:p0 + p1" not in html  # the internal key must not leak to the card


def test_manifesto_card_empty_on_fresh_project(tmp_path):
    assert _manifesto_section(str(tmp_path)) == ""


def test_manifesto_card_empty_on_malformed_history(tmp_path):
    """Corrupt evidence degrades to an empty manifesto (never raises) — the
    card self-gates to "" exactly like a fresh project."""
    apex = tmp_path / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-of-fix.json").write_text("{ not valid json", encoding="utf-8")
    assert _manifesto_section(str(tmp_path)) == ""


def test_manifesto_card_is_deterministic(tmp_path):
    _learned_project(tmp_path)
    assert _manifesto_section(str(tmp_path)) == _manifesto_section(str(tmp_path))


def test_manifesto_card_tolerates_a_nonexistent_root():
    # No project at all -> derive_manifesto sees no .apex history -> "".
    assert _manifesto_section("/nonexistent-root-for-manifesto-card-xyz") == ""


# --- RenderedSections / nav wiring ------------------------------------------

def test_rendered_sections_has_manifesto_field():
    empty = RenderedSections()
    assert empty.manifesto_html == ""
    bundle = RenderedSections(manifesto_html="<m>")
    assert bundle.manifesto_html == "<m>"


def test_nav_link_gated_on_manifesto_html():
    """`_nav_links` mirrors section gating: the Manifesto anchor appears iff
    `sections.manifesto_html` is non-empty — exactly like `nativemind`."""
    base = dict(
        project_root="/nonexistent-root-xyz",
        git={}, debug={}, roadmap=None, shape=None, autonomy=None,
        pareto=[], trajectory=[], learned=None,
    )
    absent = d._nav_links(**base, sections=RenderedSections())
    assert "href='#manifesto'" not in absent

    present = d._nav_links(
        **base,
        sections=RenderedSections(manifesto_html="<section id='manifesto'></section>"),
    )
    assert "href='#manifesto'" in present
    assert ">Manifesto<" in present


def test_page_sections_places_manifesto_between_overview_and_actions(tmp_path):
    """`_page_sections` concatenates the pre-rendered fragment verbatim, in the
    documented page position: after the "living-cell" cards, before Actions."""
    _small_python_project(tmp_path)
    _learned_project(tmp_path)
    html_doc = d.build_dashboard(str(tmp_path), max_ideas=12, quality=False)
    main = html_doc.split("<main>", 1)[1].split("</main>", 1)[0]
    overview_pos = main.find("id='overview'")
    manifesto_pos = main.find("id='manifesto'")
    actions_pos = main.find("id='actions'")
    assert overview_pos != -1 and manifesto_pos != -1 and actions_pos != -1
    assert overview_pos < manifesto_pos < actions_pos


# --- End-to-end wiring via build_dashboard -----------------------------------

def test_build_dashboard_shows_manifesto_card_for_a_learned_project(tmp_path):
    _small_python_project(tmp_path)
    _learned_project(tmp_path)
    html = d.build_dashboard(str(tmp_path), max_ideas=12, quality=False)
    assert "id='manifesto'" in html
    assert "href='#manifesto'" in html
    assert "Living manifesto" in html


def test_build_dashboard_omits_manifesto_card_for_a_fresh_project(tmp_path):
    """A fresh project (no `.apex` history) renders no manifesto card/nav link —
    the page stays byte-identical to before this feature existed."""
    _small_python_project(tmp_path)
    html = d.build_dashboard(str(tmp_path), max_ideas=12, quality=False)
    assert "id='manifesto'" not in html
    assert "href='#manifesto'" not in html
