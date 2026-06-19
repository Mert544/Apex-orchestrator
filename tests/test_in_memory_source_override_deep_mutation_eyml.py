"""Deep mutation-hardening pins for the in-memory dry-run path in
``app/execution/_transform_base.py``.

The simplification scanner dry-runs each on-disk ``plan_<name>(root, rel)``
transform against a source string it ALREADY holds, with no filesystem write or
re-read: it opens a ``source_override({rel: src})`` block, calls the unmodified
transform with ``IN_MEMORY_ROOT`` as the project root, and ``read_module_source``
returns the registered source verbatim instead of touching disk. This battery
pins the load-bearing invariants of that path so a mutation to any of them is
caught:

  - inside the block, reading the registered ``rel`` returns EXACTLY ``src``
    (byte-identical) and never touches disk;
  - OUTSIDE the block (and after it exits) the override is gone — a read of the
    same ``rel`` falls through to disk;
  - the override is THREAD-LOCAL: a second thread spun inside the block never
    sees this thread's injected sources (proven by spinning a real thread);
  - a stray read under ``IN_MEMORY_ROOT`` for an UNregistered ``rel`` fails
    closed (records a "cannot read" blocker, returns None — no real file read);
  - the context manager restores/clears the previous override state on normal
    exit AND on an exception propagating out of the block.

Every assertion targets an exact value, the override map identity, or the
blocker text. Nothing depends on a wall clock, set/dict iteration order, or real
git history, so the pins are deterministic and reproducible.

Style mirrors ``test_simplification_scan_perf_eyml.py`` and
``test_project_profile_deep_mutation_eyml.py``: direct calls to the primitives
and tight value assertions, no broad-suite dependency.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.execution import _transform_base as tb
from app.execution._transform_base import (
    IN_MEMORY_ROOT,
    read_module_source,
    source_override,
)


class _Plan:
    """A minimal stand-in for a plan: ``read_module_source`` only needs a
    ``blockers`` list to record a failed-read blocker against."""

    def __init__(self) -> None:
        self.blockers: list[str] = []


# --------------------------------------------------------------------------- #
# IN_MEMORY_ROOT sentinel value.
# --------------------------------------------------------------------------- #

def test_in_memory_root_is_the_sentinel_marker():
    """The sentinel root is the exact unreal-path marker (L81).

    It must be a path that can never exist on a real tree, so an accidental
    fall-through to a disk read under it fails closed.
    """
    assert IN_MEMORY_ROOT == "<apex-in-memory>"
    assert not Path(IN_MEMORY_ROOT).exists()


# --------------------------------------------------------------------------- #
# read_module_source: registered override returns the source verbatim, no disk.
# --------------------------------------------------------------------------- #

def test_registered_override_returns_exact_source_no_disk():
    """Inside a ``source_override`` block, reading the registered ``rel`` under
    ``IN_MEMORY_ROOT`` returns EXACTLY the registered string (L136-L138).

    The returned text is byte-identical to ``src`` and no blocker is recorded,
    proving the disk read at L139-L141 was never reached (``IN_MEMORY_ROOT`` is
    an unreal path — a disk read there would fail and record a blocker).
    """
    rel = "pkg/mod.py"
    src = "def f(x):\n    return x is 5\n"
    plan = _Plan()
    with source_override({rel: src}):
        got = read_module_source(plan, IN_MEMORY_ROOT, rel)
    assert got == src
    assert got is src  # returned verbatim, not a copy/re-encode
    assert plan.blockers == []


def test_registered_override_distinguishes_keys():
    """With several keys registered, each ``rel`` returns its OWN source (L137
    ``module_rel in overrides`` + L138 ``overrides[module_rel]``)."""
    sources = {"a/x.py": "AAA\n", "b/y.py": "BBB\n"}
    plan = _Plan()
    with source_override(sources):
        assert read_module_source(plan, IN_MEMORY_ROOT, "a/x.py") == "AAA\n"
        assert read_module_source(plan, IN_MEMORY_ROOT, "b/y.py") == "BBB\n"
    assert plan.blockers == []


# --------------------------------------------------------------------------- #
# Fail-closed: unregistered rel under IN_MEMORY_ROOT records a blocker, no read.
# --------------------------------------------------------------------------- #

def test_unregistered_rel_under_in_memory_root_fails_closed():
    """A read of an UNregistered ``rel`` while an override is active falls through
    to the (unreal) ``IN_MEMORY_ROOT`` disk path and fails closed (L139-L144).

    It returns None and appends EXACTLY ``cannot read <rel>`` — never a stray
    real file. The exact blocker text is pinned so a mutation of the f-string is
    caught.
    """
    plan = _Plan()
    with source_override({"registered.py": "X\n"}):
        got = read_module_source(plan, IN_MEMORY_ROOT, "unregistered.py")
    assert got is None
    assert plan.blockers == ["cannot read unregistered.py"]


def test_in_memory_root_with_no_active_override_fails_closed():
    """With NO override active, a read under ``IN_MEMORY_ROOT`` fails closed
    (L136 ``overrides is None`` -> straight to the disk path).

    No file can exist at the sentinel root, so the read records a blocker and
    returns None rather than reading a real file.
    """
    plan = _Plan()
    got = read_module_source(plan, IN_MEMORY_ROOT, "pkg/mod.py")
    assert got is None
    assert plan.blockers == ["cannot read pkg/mod.py"]


# --------------------------------------------------------------------------- #
# Outside / after the block the override is gone (falls through to disk).
# --------------------------------------------------------------------------- #

def test_override_inactive_before_block(tmp_path: Path):
    """Before any block is opened, ``read_module_source`` reads from DISK — the
    registered source is not consulted (L136 ``overrides is None``)."""
    (tmp_path / "m.py").write_text("DISK\n", encoding="utf-8")
    plan = _Plan()
    assert read_module_source(plan, tmp_path, "m.py") == "DISK\n"
    assert plan.blockers == []


def test_override_does_not_leak_after_block(tmp_path: Path):
    """After the block exits, the same ``rel`` reads from DISK again, NOT the
    (now stale) injected source — the finally clause cleared it (L114-L115).

    The on-disk content differs from the injected content, so a leak would be
    visible as the wrong string.
    """
    rel = "m.py"
    (tmp_path / rel).write_text("DISK\n", encoding="utf-8")
    plan = _Plan()
    with source_override({rel: "MEMORY\n"}):
        assert read_module_source(plan, tmp_path, rel) == "MEMORY\n"
    # After exit the override is gone: the on-disk file wins.
    assert read_module_source(plan, tmp_path, rel) == "DISK\n"
    assert tb._active_source_overrides() is None
    assert plan.blockers == []


# --------------------------------------------------------------------------- #
# _active_source_overrides reflects the registered map exactly.
# --------------------------------------------------------------------------- #

def test_active_overrides_none_outside_block():
    """With no block active, ``_active_source_overrides`` is None (L95 default)."""
    assert tb._active_source_overrides() is None


def test_active_overrides_is_the_registered_map_inside_block():
    """Inside the block, ``_active_source_overrides`` IS the exact registered
    dict (L111 ``_SOURCE_OVERRIDES.stack = sources``)."""
    sources = {"pkg/mod.py": "SRC\n"}
    with source_override(sources):
        assert tb._active_source_overrides() is sources
    assert tb._active_source_overrides() is None


# --------------------------------------------------------------------------- #
# Nested blocks compose and restore the PREVIOUS map (not just clear to None).
# --------------------------------------------------------------------------- #

def test_nested_blocks_restore_previous_override():
    """A nested block restores the OUTER override map on exit, not None (L110
    ``previous = ...`` / L115 ``= previous``).

    Inside the inner block the inner map is active; after the inner block exits,
    the OUTER map is active again — proving the finally restores ``previous``,
    not a hardcoded None.
    """
    outer = {"o.py": "OUTER\n"}
    inner = {"i.py": "INNER\n"}
    with source_override(outer):
        assert tb._active_source_overrides() is outer
        with source_override(inner):
            assert tb._active_source_overrides() is inner
        # Inner exited -> outer restored (NOT cleared to None).
        assert tb._active_source_overrides() is outer
    assert tb._active_source_overrides() is None


# --------------------------------------------------------------------------- #
# State is restored/cleared even when an exception propagates out of the block.
# --------------------------------------------------------------------------- #

def test_override_cleared_on_exception():
    """An exception raised inside the block still clears the override (the
    ``finally`` at L112-L115 runs on the exception path)."""
    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with source_override({"m.py": "X\n"}):
            assert tb._active_source_overrides() is not None
            raise _Boom
    assert tb._active_source_overrides() is None


def test_nested_override_restored_to_previous_on_exception():
    """An exception in a NESTED block restores the OUTER map, not None (the
    ``finally`` restores ``previous`` on the exception path too)."""
    class _Boom(Exception):
        pass

    outer = {"o.py": "OUTER\n"}
    with source_override(outer):
        with pytest.raises(_Boom):
            with source_override({"i.py": "INNER\n"}):
                raise _Boom
        assert tb._active_source_overrides() is outer
    assert tb._active_source_overrides() is None


# --------------------------------------------------------------------------- #
# Thread-local isolation: a second thread never sees this thread's overrides.
# --------------------------------------------------------------------------- #

def test_override_is_thread_local():
    """The override registry is thread-local: a thread spun INSIDE an active
    block sees NO override, and a read it performs under ``IN_MEMORY_ROOT`` for
    the registered ``rel`` fails closed (L89 ``threading.local()``).

    Spinning a real thread proves the isolation — if the registry were a module
    global, the worker would see the injected source.
    """
    rel = "pkg/mod.py"
    seen: dict[str, object] = {}

    def worker() -> None:
        seen["active"] = tb._active_source_overrides()
        plan = _Plan()
        seen["read"] = read_module_source(plan, IN_MEMORY_ROOT, rel)
        seen["blockers"] = list(plan.blockers)

    with source_override({rel: "MAIN_THREAD\n"}):
        # Main thread sees the override...
        main_plan = _Plan()
        assert read_module_source(main_plan, IN_MEMORY_ROOT, rel) == "MAIN_THREAD\n"
        # ...but a worker thread spun inside the block does not.
        t = threading.Thread(target=worker)
        t.start()
        t.join()

    assert seen["active"] is None
    assert seen["read"] is None
    assert seen["blockers"] == ["cannot read pkg/mod.py"]
