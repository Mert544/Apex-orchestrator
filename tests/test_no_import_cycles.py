"""Regression guard: the organism keeps its OWN app/ package acyclic.

Apex grades projects on import cycles; it must hold itself to the same bar.
A real cycle was introduced (exposure <-> project_profile) and caught by the
grade — this freezes the fix so it can't silently come back.
"""

from __future__ import annotations

from app.tools.dependency_graph import DependencyGraphBuilder


def test_app_package_has_no_import_cycles():
    cycles = DependencyGraphBuilder("app").find_cycles(limit=10)
    assert cycles == [], f"import cycle(s) reintroduced: {cycles}"
