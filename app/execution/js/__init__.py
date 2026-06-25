"""Apex's JS/TS support — its first non-Python concrete landing.

All JS/TS machinery is isolated under this package so the Python path stays
byte-identical: a bundled, deterministic ``ts_driver.js`` (the global TypeScript
Compiler API for exact byte-span parse/transform), a thin Python wrapper
(:mod:`app.execution.js.js_tool`) that spawns it via the existing
:class:`~app.runtime.command_runner.CommandRunner`, and the LLM-free template
space + jest gate-driver (:mod:`app.execution.js.js_stub_synthesis`). The
self-registering objective lives at
``app.execution.objectives.js_tdd_implement``.
"""

from __future__ import annotations

__all__: list[str] = []
