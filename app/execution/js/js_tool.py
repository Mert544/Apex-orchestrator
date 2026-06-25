"""Thin Python wrapper around the bundled ``ts_driver.js`` — the ONE place that
knows the node invocation for Apex's JS/TS support.

Every JS/TS parse/transform Apex does goes through this module: it builds a
:class:`CommandSpec` and runs it on the EXISTING :class:`CommandRunner` (so the
``node`` allow-list entry and the subprocess discipline are shared with the rest
of Apex), passing ``NODE_PATH`` so the driver's ``require("typescript")``
resolves to the globally-installed compiler regardless of the target project's
own ``node_modules``. The driver speaks canonical JSON on stdout and exits 2 on
REFUSE; a non-zero exit (refusal, missing node, or any error) is read
CONSERVATIVELY here as "no result", so an ambiguous file lands nothing rather
than guessing — the JS image of the Python path's refusal discipline.

Deterministic and offline: ``ts.createSourceFile`` is a pure function of the
bytes, the driver emits stable JSON, and no clock/random is consulted, so the
same project yields byte-identical results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.runtime.command_runner import CommandResult, CommandRunner, CommandSpec

__all__ = [
    "JsStub",
    "JsWitness",
    "DRIVER",
    "global_node_modules",
    "scan_stubs",
    "mine_witnesses",
    "fill_body",
]

# The bundled driver checked into this package — never a string Apex generates.
DRIVER = Path(__file__).with_name("ts_driver.js")


@dataclass(frozen=True)
class JsStub:
    """One top-level ``throw``-stub function the driver found, with the exact byte
    span of its body block (``body_start`` = the ``{``, ``body_end`` = just past
    the ``}``) so a fill is a precise splice, not an unparse."""

    name: str
    params: tuple[str, ...]
    body_start: int
    body_end: int


@dataclass(frozen=True)
class JsWitness:
    """One ``expect(name(args)).matcher(expected)`` example a jest test pins, as
    the literal source bytes of the arguments and the expected value — the
    ``(args, expected)`` tuple the synthesiser's gate and constant floor use."""

    args: tuple[str, ...]
    expected: str


@lru_cache(maxsize=1)
def global_node_modules() -> str:
    """``npm root -g`` — the global ``node_modules`` dir holding ``typescript`` —
    so the driver's ``require("typescript")`` resolves. Memoized (a pure function
    of the install) and conservative: an empty string when ``npm`` cannot answer,
    which simply leaves ``NODE_PATH`` unset (the driver then refuses, landing
    nothing)."""
    try:
        res = CommandRunner().run(CommandSpec(command=["npm", "root", "-g"]))
    except Exception:
        return ""
    return res.stdout.strip() if res.ok else ""


def _run_driver(args: list[str], cwd: Path) -> CommandResult | None:
    """Spawn ``node ts_driver.js <args>`` with ``NODE_PATH`` set, or ``None`` when
    the runner refuses/raises. The single seam every driver call funnels through."""
    env = {}
    node_path = global_node_modules()
    if node_path:
        env["NODE_PATH"] = node_path
    try:
        return CommandRunner().run(CommandSpec(
            command=["node", str(DRIVER), *args], cwd=cwd, env=env or None))
    except Exception:
        return None


def _driver_json(args: list[str], cwd: Path):
    """The parsed JSON the driver printed for ``args``, or ``None`` on ANY failure
    (refusal/exit-2, missing node, unparseable output). Conservative by design —
    a ``None`` is read by callers as "refuse / nothing to do"."""
    res = _run_driver(args, cwd)
    if res is None or not res.ok:
        return None
    try:
        return json.loads(res.stdout)
    except (ValueError, TypeError):
        return None


def scan_stubs(root: Path, rel: str) -> list[JsStub]:
    """The top-level ``throw``-stub functions in ``root/rel`` (empty on refuse).

    A file that does not parse, has no fillable stub, or that the driver declines
    yields ``[]`` — nothing to do, never a guess."""
    data = _driver_json(["scan", str(root / rel)], root)
    if not isinstance(data, list):
        return []
    return [JsStub(name=d["name"], params=tuple(d["params"]),
                   body_start=d["bodyStart"], body_end=d["bodyEnd"])
            for d in data]


def mine_witnesses(root: Path, test_rel: str, name: str) -> list[JsWitness]:
    """The witness tuples the jest test ``root/test_rel`` pins on ``name`` (empty
    when none / on refuse). Deterministic source order, as the driver emits."""
    data = _driver_json(["mine", str(root / test_rel), name], root)
    if not isinstance(data, list):
        return []
    return [JsWitness(args=tuple(d["args"]), expected=d["expected"]) for d in data]


def fill_body(root: Path, rel: str, name: str, body: str) -> bool:
    """Splice ``{ <body> }`` over the body block of the single stub ``name`` in
    ``root/rel``, writing the file in place. ``True`` on success, ``False`` when
    the driver refused (``name`` not a unique fillable stub) so nothing changed.

    This is the in-place editing primitive the synthesiser uses against a
    THROWAWAY copy while probing templates; the LANDED change is carried as a
    :class:`RenamePlan` and applied by the gated/rollback writer, never here."""
    res = _run_driver(["fill", str(root / rel), name, body], root)
    return bool(res is not None and res.ok)
