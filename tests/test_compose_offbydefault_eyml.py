"""Off-by-default byte-identity for the multi-file composition primitive.

``compose_plans`` / ``multifile_landing`` are COMPOSITION PRIMITIVES, not develop
objectives: they never ``register()``. So importing them must change NOTHING the
develop/audit surfaces observe — the available-objective set, the soundness
verdict, and the facet-route parity are all byte-identical with or without the
new modules imported. This is the invariant that lets the increment ship without
shifting any existing campaign.
"""

from __future__ import annotations


def test_available_objectives_unchanged():
    from app.engine.objective_compiler import available_objectives

    before = sorted(available_objectives())

    # Importing the new modules must NOT register anything.
    import app.execution.compose_plans  # noqa: F401
    import app.execution.multifile_landing  # noqa: F401

    after = sorted(available_objectives())
    assert after == before
    # The composed operator names never enter the objective set.
    assert "implement-and-wire" not in after
    assert "compose" not in after


def test_new_modules_register_nothing():
    # The single-gated-writer / off-by-default guarantee at the registry level:
    # neither new module appears among the self-registered objective specs.
    import app.execution.compose_plans  # noqa: F401
    import app.execution.multifile_landing  # noqa: F401
    from app.engine.develop_registry import registered_specs

    names = set(registered_specs())
    assert "implement-and-wire" not in names
    assert "compose" not in names


def test_soundness_audit_still_passes():
    import app.execution.compose_plans  # noqa: F401
    import app.execution.multifile_landing  # noqa: F401
    from app.engine.soundness_audit import soundness_report

    report = soundness_report(".")
    assert report["verdict"] == "PASS"
    # No manifest/parity drift: every live objective still has a strategy, and the
    # single gated writer (A1) is intact (no new apply_rename call site).
    assert report["single_writer_ok"] is True


def test_facet_parity_unaffected():
    import app.execution.compose_plans  # noqa: F401
    import app.execution.multifile_landing  # noqa: F401
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    # The 1:1 facet-route parity the suite enforces still holds — the primitive is
    # invisible to the facet map because it never registered.
    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())
