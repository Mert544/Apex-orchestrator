# Soundness adversarial corpus

A fixed set of tiny library-shaped projects, each embedding ONE adversarial
shape that Apex's OWN application tree lacks (no `setup.py`, no shebang scripts
under scan, no external subclasser, no env-fragile public return). Every
registered develop objective is run against each shape by
`app/engine/soundness_audit.py` and must **refuse or stay behavior-identical** —
the deterministic, in-repo substitute for the foreign-repo pilot that historically
caught unsound transforms only after they shipped A+99-test-green.

These projects are intentionally NOT importable test modules — they live under
`tests/fixtures/` so the real suite never collects them, and each fixture's
`pkg/` is a self-contained project root the audit passes to an objective's
`moves(<fixture-root>)`.

Each shape's `pkg/__init__.py` is empty so the inner modules are real LIBRARY
modules (an objective's eligibility gate accepts them); the audit treats the
fixture's own root as the scan root, so a subclass placed under the fixture's
`tests/` directory is still seen by the tests-INCLUSIVE over-approximate scans
(the exact false-final shape the K2 re-audit flagged).

DO NOT add a top-level side effect (a bare `print`, a module-level call) to any
fixture: the determinism probe imports them in a subprocess, and a side effect
would leak to stdout and break the byte-identical comparison.
