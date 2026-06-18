"""render_discoveries_markdown — the non-competing surface for emergent discoveries.

The dream's open-ended discovery finds "what travels with what" on THIS codebase
but was kept out of the bounded idea tree. ``render_discoveries_markdown`` gives
those discoveries their own Markdown section instead. These tests pin the
rendering shape (heading + one bullet per pattern, naming module + pattern +
confidence/support), determinism, the empty/below-threshold state, and that the
output is always valid Markdown that never raises.
"""

from __future__ import annotations

from app.reporting.discoveries_section import render_discoveries_markdown
from app.tools.project_profile import ProjectProfile

_HEADING = "# Emergent discoveries"


def _cooccurring_profile() -> ProjectProfile:
    # Every single-author module here is also high-churn -> a discovered law.
    return ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/a.py", "commits": 9},
                        {"module": "app/b.py", "commits": 8},
                        {"module": "app/quiet.py", "commits": 7}],
        knowledge_risks=[{"module": "app/a.py", "share": 100, "commits": 9},
                         {"module": "app/b.py", "share": 90, "commits": 8}],
    )


def _broad_profile() -> ProjectProfile:
    # One module carries many distinct signals -> a confluence, bound to it.
    return ProjectProfile(
        root=".",
        security_finding_modules=["app/hot.py"],
        untested_modules=["app/hot.py", "app/x.py"],
        fragile_modules=["app/hot.py"],
        debt_marker_modules=["app/hot.py", "app/y.py"],
    )


def test_starts_with_heading_and_is_valid_markdown():
    out = render_discoveries_markdown(_cooccurring_profile())
    assert out.startswith(_HEADING)
    assert out.endswith("\n")


def test_renders_a_bullet_per_discovered_pattern():
    out = render_discoveries_markdown(_cooccurring_profile())
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert bullets, "a co-occurring signal pair should render at least one bullet"
    # Each bullet names the discovery kind and its confidence/support.
    for bullet in bullets:
        assert bullet.startswith("- **")
        assert "confidence" in bullet
        assert "support" in bullet


def test_association_bullet_carries_the_pattern_text():
    out = render_discoveries_markdown(_cooccurring_profile())
    assert "single-author" in out
    assert "high-churn" in out
    assert "**association**" in out


def test_confluence_bullet_names_its_module():
    out = render_discoveries_markdown(_broad_profile())
    assert "**confluence**" in out
    # The confluence is grounded in the concrete broad module.
    assert "in `app/hot.py`" in out


def test_deterministic_across_calls():
    profile = _cooccurring_profile()
    assert render_discoveries_markdown(profile) == render_discoveries_markdown(profile)


def test_empty_profile_renders_empty_state():
    out = render_discoveries_markdown(ProjectProfile(root="."))
    assert out.startswith(_HEADING)
    assert "No emergent patterns found" in out
    assert not any(ln.startswith("- ") for ln in out.splitlines())


def test_below_threshold_profile_renders_empty_state():
    # A single co-occurrence is a coincidence, not a discovered law.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py"],
        untested_modules=["app/a.py"],
    )
    out = render_discoveries_markdown(profile)
    assert "No emergent patterns found" in out


def test_never_raises_on_odd_profile():
    # Missing / empty fields must degrade to the empty state, not an error.
    out = render_discoveries_markdown(ProjectProfile(root="."))
    assert isinstance(out, str) and out


def test_bullet_count_is_capped():
    from app.reporting.discoveries_section import _MAX_BULLETS
    mods = [f"app/m{i}.py" for i in range(8)]
    profile = ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
        fragile_modules=list(mods),
        debt_marker_modules=list(mods),
    )
    out = render_discoveries_markdown(profile)
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(bullets) <= _MAX_BULLETS
