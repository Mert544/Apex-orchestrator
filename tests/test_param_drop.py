"""Parameter drop: def site rebuilt + keyword call sites pruned, conservatively."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.param_drop import plan_param_drop


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    # color was never wired up\n"
        "    return text[:width]\n"
    )
    (tmp_path / "app" / "kw_user.py").write_text(
        "from app.core import render\n"
        "\n"
        "def f(t):\n"
        "    return render(t, color='red', width=40)\n"
    )
    (tmp_path / "app" / "attr_user.py").write_text(
        "import app.core\n"
        "\n"
        "def h(t):\n"
        "    return app.core.render(t, color='blue')\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import render\n"
        "def test_render():\n"
        "    assert render('hello', width=2) == 'he'\n"
    )
    return tmp_path


def test_plan_rebuilds_def_and_prunes_keyword_call_sites(tmp_path):
    _project(tmp_path)
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    core = plan.new_contents["app/core.py"]
    assert "def render(text, width=80):" in core
    assert "# color was never wired up" in core  # body comments untouched
    assert "render(t, width=40)" in plan.new_contents["app/kw_user.py"]
    assert "app.core.render(t)" in plan.new_contents["app/attr_user.py"]
    # The call site that never passed it stays out of the plan.
    assert "tests/test_core.py" not in plan.new_contents
    # Every rewritten file still parses.
    import ast
    for text in plan.new_contents.values():
        ast.parse(text)


def test_first_keyword_argument_drop_eats_following_comma(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "first.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, **{}) or render(color='x', text=t)\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    assert "render(text=t)" in plan.new_contents["app/first.py"]
    assert any("may still carry 'color'" in w for w in plan.warnings)


def test_positional_call_site_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "pos.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, 'red')\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert not plan.ok
    assert any("POSITIONALLY" in b for b in plan.blockers)
    assert not plan.new_contents  # a blocked plan proposes nothing


def test_param_actually_read_blocks(tmp_path):
    _project(tmp_path)
    plan = plan_param_drop(tmp_path, "render", "width")  # body uses width
    assert not plan.ok
    assert any("READS" in b for b in plan.blockers)


def test_signature_validation_blocks(tmp_path):
    _project(tmp_path)
    assert not plan_param_drop(tmp_path, "ghost", "color").ok   # no function
    assert not plan_param_drop(tmp_path, "render", "nope").ok   # not a param
    (tmp_path / "app" / "var.py").write_text(
        "def collect(*items, **extra):\n    return len(items) + len(extra)\n")
    assert not plan_param_drop(tmp_path, "collect", "items").ok  # *args
    assert not plan_param_drop(tmp_path, "collect", "extra").ok  # **kwargs


def test_comment_inside_signature_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def render(text,\n"
        "           color=None,  # never used\n"
        "           width=80):\n"
        "    return text[:width]\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert not plan.ok
    assert any("comment" in b for b in plan.blockers)


def test_multiline_signature_collapses_cleanly(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def render(text,\n"
        "           color=None,\n"
        "           width=80):\n"
        "    return text[:width]\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    assert "def render(text, width=80):" in plan.new_contents["app/core.py"]


def test_multiline_def_with_same_file_call_site_below(tmp_path):
    # Found by dogfooding on Apex itself: collapsing a 2-line header shifts
    # every line below it — a same-file call site pruned with the ORIGINAL
    # line numbers then mangles the wrong line. Call sites must be pruned
    # first (intra-line, numbering-safe), the header rebuilt last.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def render(text, color=None,\n"
        "           width=80):\n"
        "    return text[:width]\n"
        "\n"
        "def page(t):\n"
        "    return render(t, color='red',\n"
        "                  width=40)\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    core = plan.new_contents["app/core.py"]
    import ast
    ast.parse(core)  # the mangled version was a SyntaxError
    assert "def render(text, width=80):" in core
    assert "render(t,\n" in core or "render(t, width=40)" in core
    assert "width=40)" in core


def test_keyword_alone_on_its_line_warns_about_ragged_call(tmp_path):
    # Found applying the engine's own recommendation on safety_gates: the
    # separating comma lives on the line above, out of reach for an
    # intra-line edit — the result is valid (trailing comma) but ragged,
    # and the plan must SAY so.
    _project(tmp_path)
    (tmp_path / "app" / "tall.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t,\n"
        "                  color='red')\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    import ast
    ast.parse(plan.new_contents["app/tall.py"])  # valid, comma-trailing
    assert any("ragged" in w for w in plan.warnings)


def test_multiline_keyword_value_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "tall.py").write_text(
        "from app.core import render\n"
        "def g(t):\n"
        "    return render(t, color=(\n"
        "        'red'))\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert not plan.ok
    assert any("spans lines" in b for b in plan.blockers)


def test_annotated_defaults_keep_pep8_spacing(tmp_path):
    # Found dropping `objective` from build_city_model on the live repo:
    # the rebuild wrote `max_buildings: int=60`. Annotated params get
    # spaces around "=", unannotated ones stay tight.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def render(text: str, color=None, width: int = 80, pad=0):\n"
        "    return text[: width + pad]\n"
    )
    plan = plan_param_drop(tmp_path, "render", "color")
    assert plan.ok, plan.blockers
    assert "def render(text: str, width: int = 80, pad=0):" in plan.new_contents["app/core.py"]


def test_kwonly_and_posonly_shapes_survive(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "shapes.py").write_text(
        "def kw_fn(a, *, flag=False, depth=1):\n"
        "    return a + depth\n"
        "\n"
        "def pos_fn(probe, /, rest=0):\n"
        "    return rest\n"
        "\n"
        "def star_fn(a, *items, trace=None):\n"
        "    return a + len(items)\n"
    )
    kw_plan = plan_param_drop(tmp_path, "kw_fn", "flag")
    assert kw_plan.ok, kw_plan.blockers
    assert "def kw_fn(a, *, depth=1):" in kw_plan.new_contents["app/shapes.py"]

    # Dropping the SOLE positional-only param must not leave a dangling "/".
    pos_plan = plan_param_drop(tmp_path, "pos_fn", "probe")
    assert pos_plan.ok, pos_plan.blockers
    assert "def pos_fn(rest=0):" in pos_plan.new_contents["app/shapes.py"]

    # A *args keeps kwonly params reachable — no bare "*" needed.
    star_plan = plan_param_drop(tmp_path, "star_fn", "trace")
    assert star_plan.ok, star_plan.blockers
    assert "def star_fn(a, *items):" in star_plan.new_contents["app/shapes.py"]


def test_bare_star_dropped_with_last_kwonly(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "solo.py").write_text(
        "def fetch(url, *, retries=3):\n"
        "    return url\n"
    )
    plan = plan_param_drop(tmp_path, "fetch", "retries")
    assert plan.ok, plan.blockers
    assert "def fetch(url):" in plan.new_contents["app/solo.py"]


def test_apply_verifies_and_rolls_back(tmp_path):
    _project(tmp_path)
    res = apply_rename(tmp_path, plan_param_drop(tmp_path, "render", "color"),
                       verify=True)
    assert res["applied"] is True and res["verified"] is True
    core = (tmp_path / "app" / "core.py").read_text()
    assert "def render(text, width=80):" in core
    assert "# color was never wired up" in core  # the comment survives the drop

    # Now a red suite: everything must come back.
    (tmp_path / "tests" / "test_red.py").write_text("def test_red():\n    assert False\n")
    before = (tmp_path / "app" / "core.py").read_text()
    res2 = apply_rename(tmp_path, plan_param_drop(tmp_path, "render", "width"),
                        verify=True)
    # width is read by the body, so this plan is blocked, not rolled back —
    # use a genuinely unused param to exercise the rollback path instead.
    (tmp_path / "app" / "core.py").write_text(
        "def render(text, width=80, pad=0):\n    return text[:width]\n")
    res2 = apply_rename(tmp_path, plan_param_drop(tmp_path, "render", "pad"),
                        verify=True)
    assert res2["applied"] is False and res2["rolled_back"] is True
    assert "pad=0" in (tmp_path / "app" / "core.py").read_text()
    assert before  # the earlier snapshot stayed comparable


def test_cli_signature_drop(tmp_path, capsys):
    from app.cli import cmd_signature

    _project(tmp_path)
    ns = argparse.Namespace(op="drop", function="render", param="color",
                            target=str(tmp_path), dry_run=True, no_verify=False,
                            json=False)
    assert cmd_signature(ns) == 0
    out = capsys.readouterr().out
    assert "-def render(text, color=None, width=80):" in out
    assert "+def render(text, width=80):" in out

    ns.dry_run = False
    assert cmd_signature(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert "color" not in (tmp_path / "app" / "kw_user.py").read_text()

    # A blocked drop reports the blocker and exits 1.
    ns2 = argparse.Namespace(op="drop", function="render", param="width",
                             target=str(tmp_path), dry_run=True, no_verify=False,
                             json=False)
    assert cmd_signature(ns2) == 1
    assert "⛔" in capsys.readouterr().out


def _plan_fingerprint(plan):
    """Order-stable structural snapshot of a plan — what callers observe."""
    return (
        plan.old, plan.new, plan.defined_in,
        sorted(plan.blockers), sorted(plan.warnings),
        sorted(plan.new_contents.items()),
        sorted(plan.originals.items()),
        sorted(plan.edits_by_file.items()),
    )


def test_plan_is_pinned_for_the_canonical_drop(tmp_path):
    """Characterization: the canonical multi-call drop produces this exact
    plan. Pins the refactored decomposition byte-for-byte against the
    behavior it replaced — any drift here is an unintended logic change."""
    _project(tmp_path)
    plan = plan_param_drop(tmp_path, "render", "color")

    assert plan.old == "color"
    assert plan.new == ""
    assert plan.defined_in == "app/core.py"
    assert plan.blockers == []
    assert plan.warnings == []
    assert plan.new_contents == {
        "app/core.py": (
            "def render(text, width=80):\n"
            "    # color was never wired up\n"
            "    return text[:width]\n"
        ),
        "app/kw_user.py": (
            "from app.core import render\n"
            "\n"
            "def f(t):\n"
            "    return render(t, width=40)\n"
        ),
        "app/attr_user.py": (
            "import app.core\n"
            "\n"
            "def h(t):\n"
            "    return app.core.render(t)\n"
        ),
    }
    assert plan.edits_by_file == {
        "app/core.py": 1, "app/kw_user.py": 1, "app/attr_user.py": 1,
    }
    # The originals captured for rollback match the on-disk sources exactly.
    for rel, original in plan.originals.items():
        assert original == (tmp_path / rel).read_text()


def test_plan_fingerprint_stable_across_repeated_runs(tmp_path):
    """Determinism: re-planning the same project yields an identical plan."""
    _project(tmp_path)
    first = _plan_fingerprint(plan_param_drop(tmp_path, "render", "color"))
    second = _plan_fingerprint(plan_param_drop(tmp_path, "render", "color"))
    assert first == second


def test_plan_pinned_for_blocked_positional_call(tmp_path):
    """Characterization of the empty/blocked path: a positional pass blocks
    the drop and clears every staged edit."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def g(a, b, c):\n    return a\n"
    )
    (tmp_path / "app" / "caller.py").write_text(
        "from app.core import g\ndef f():\n    return g(1, 2, 3)\n"
    )
    plan = plan_param_drop(tmp_path, "g", "b")
    assert not plan.ok
    assert plan.blockers == [
        "app/caller.py:3: passes 'b' POSITIONALLY — "
        "convert that call to keywords first, then re-run"
    ]
    assert plan.new_contents == {}
    assert plan.originals == {}
    assert plan.edits_by_file == {}
