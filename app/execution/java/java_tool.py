"""Thin Python wrapper around the bundled ``ApexJavaDriver.java`` — the ONE place
that knows the ``java`` invocation for Apex's Java support.

The Java sibling of :mod:`app.execution.js.js_tool`. Every Java parse/analyse Apex
does goes through this module: it builds a :class:`CommandSpec` and runs it on the
EXISTING :class:`CommandRunner` (so the ``java`` allow-list entry and the subprocess
discipline are shared with the rest of Apex), invoking the checked-in driver as a
JDK single-file source launcher (``java ApexJavaDriver.java <subcommand> <file>``).
The driver speaks canonical JSON on stdout and exits 2 on REFUSE; a non-zero exit
(refusal, missing JDK, or any error) is read CONSERVATIVELY here as "no result", so
an ambiguous file lands nothing rather than guessing — the Java image of the Python
path's refusal discipline.

Unlike the JS bridge there is NO ``NODE_PATH``/global-package analogue: the parser
is the JDK's OWN ``com.sun.source`` Compiler Tree API, shipped inside the JDK we
already require, so the install assumption is simply "a JDK is on PATH" (probed by
:func:`_jdk_ok`, the Java image of ``_node_ok``). When the JDK is absent every
driver call returns ``None`` and the caller lands nothing (a clean no-op).

Deterministic and offline: ``JavacTask.parse()`` is a pure function of the bytes,
the driver emits stable JSON (sorted fact sets, source-order targets, fixed key
order), and no clock/random is consulted, so the same project yields byte-identical
results.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.runtime.command_runner import CommandResult, CommandRunner, CommandSpec

__all__ = [
    "JavaFinalTarget",
    "JavaDocTarget",
    "JavaFacts",
    "DRIVER",
    "final_targets",
    "doc_targets",
    "parse_facts",
    "reparse_facts_identical",
]

# The bundled driver checked into this package — never a string Apex generates.
DRIVER = Path(__file__).with_name("ApexJavaDriver.java")


@dataclass(frozen=True)
class JavaFinalTarget:
    """One PRIVATE, never-reassigned instance field the driver found, with the byte
    ``insert_offset`` just past its existing modifier keywords where splicing
    ` final` makes it ``private final ...`` — a pure byte-offset insert, not an
    unparse. ``name`` is the field's simple name (advisory; the splice uses the
    offset)."""

    name: str
    insert_offset: int


@dataclass(frozen=True)
class JavaDocTarget:
    """One method that DECLARES a ``throws`` clause but carries NO Javadoc, with the
    simple type names of its declared throws clause IN SOURCE ORDER (``throws_types``)
    and the byte ``insert_offset`` at the method's start where a leading
    ``/** ... @throws <Type> ... */`` Javadoc block splices in — a pure byte-offset
    insert of a COMMENT, not an unparse. ``name`` is the method's simple name (the
    fact-only summary the block leads with). A Javadoc changes ZERO declared structure,
    so the spliced file re-parses fact-identical (see :func:`reparse_facts_identical`).
    The Java analogue of the Python ``document-raises`` ``Raises:`` target."""

    name: str
    throws_types: tuple[str, ...]
    insert_offset: int


@dataclass(frozen=True)
class JavaFacts:
    """The canonical structural fact-set of a Java source — the sorted declared
    ``types`` (qualified names), ``fields`` (``<Type>.<field>``), and ``methods``
    (``<Type>.<method>/<arity>``). The behaviour-identical oracle's witness: a
    leading modifier-only edit (`final`) changes ZERO of these, so the spliced file
    must re-parse AND carry the SAME ``JavaFacts`` (see
    :func:`reparse_facts_identical`)."""

    types: frozenset[str]
    fields: frozenset[str]
    methods: frozenset[str]


def _jdk_ok() -> bool:
    """True when a ``java`` launcher is on PATH — the minimum for the LLM-free driver
    to run. The Java image of ``_node_ok``; conservative — a missing JDK means every
    driver call returns ``None`` and the objective is a clean no-op."""
    return shutil.which("java") is not None


def _run_driver(args: list[str], cwd: Path) -> CommandResult | None:
    """Spawn ``java ApexJavaDriver.java <args>``, or ``None`` when the runner
    refuses/raises. The single seam every driver call funnels through. No env
    plumbing — the parser is in-JDK, so there is no ``NODE_PATH`` analogue."""
    try:
        return CommandRunner().run(CommandSpec(
            command=["java", str(DRIVER), *args], cwd=cwd))
    except Exception:
        return None


def _driver_json(args: list[str], cwd: Path):
    """The parsed JSON the driver printed for ``args``, or ``None`` on ANY failure
    (refusal/exit-2, missing JDK, unparseable output). Conservative by design — a
    ``None`` is read by callers as "refuse / nothing to do"."""
    res = _run_driver(args, cwd)
    if res is None or not res.ok:
        return None
    try:
        return json.loads(res.stdout)
    except (ValueError, TypeError):
        return None


def final_targets(root: Path, rel: str) -> list[JavaFinalTarget]:
    """The PRIVATE, never-reassigned instance-field targets in ``root/rel`` (empty on
    refuse). Conservative: a file that does not parse, has no such field, or that the
    driver declines yields ``[]`` — nothing to finalise, never a guess.

    Deterministic source order, exactly as the driver's ``final-targets`` emits."""
    data = _driver_json(["final-targets", str(root / rel)], root)
    if not isinstance(data, list):
        return []
    return [JavaFinalTarget(name=d["name"], insert_offset=d["insertOffset"])
            for d in data]


def doc_targets(root: Path, rel: str) -> list[JavaDocTarget]:
    """The methods in ``root/rel`` that DECLARE a ``throws`` clause but have NO Javadoc
    (empty on refuse). Conservative: a file that does not parse, has no such method, or
    that the driver declines yields ``[]`` — nothing to document, never a guess. The
    driver already applied the non-empty-throws-clause / no-existing-Javadoc gates.

    Deterministic source order, exactly as the driver's ``doc-targets`` emits. The
    ``throws`` simple type names are carried IN SOURCE ORDER (the declared contract,
    not inferred from ``throw new X()`` statements)."""
    data = _driver_json(["doc-targets", str(root / rel)], root)
    if not isinstance(data, list):
        return []
    return [JavaDocTarget(name=d["name"],
                          throws_types=tuple(d["throws"]),
                          insert_offset=d["insertOffset"])
            for d in data]


def parse_facts(root: Path, rel: str) -> JavaFacts | None:
    """The canonical structural fact-set of ``root/rel``, or ``None`` when the driver
    could not parse it (its conservative-refuse path).

    This is the behaviour-identical oracle's witness — see
    :func:`reparse_facts_identical`."""
    data = _driver_json(["parse-verify", str(root / rel)], root)
    if (not isinstance(data, dict)
            or not isinstance(data.get("types"), list)
            or not isinstance(data.get("fields"), list)
            or not isinstance(data.get("methods"), list)):
        return None
    return JavaFacts(types=frozenset(data["types"]),
                     fields=frozenset(data["fields"]),
                     methods=frozenset(data["methods"]))


def reparse_facts_identical(root: Path, rel: str, new_source: str) -> bool:
    """The behaviour-identical oracle for a ` final` splice: ``True`` iff
    ``new_source`` (the spliced bytes of ``root/rel``) RE-PARSES cleanly AND carries
    the EXACT same structural fact-set as the on-disk original.

    Adding ` final` to a never-reassigned private field changes ZERO runtime
    structure — the type/field/method fact-set is unchanged BY CONSTRUCTION; this
    check proves the splice did not corrupt the file (a broken splice would fail to
    re-parse, the driver would exit 2, and :func:`parse_facts` would return
    ``None``). The probe writes ``new_source`` to a THROWAWAY file (the real tree is
    never touched here) and asks the driver for its fact-set. Conservative: any
    driver failure (a parse diagnostic, missing JDK) yields ``None`` and we refuse
    (return ``False``) rather than land an unverified change. The Java image of
    :func:`app.execution.js.js_tool.reparse_exports_identical`."""
    import tempfile

    before = parse_facts(root, rel)
    if before is None:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "Probe.java"
        probe.write_text(new_source, encoding="utf-8")
        after = parse_facts(Path(tmp), probe.name)
    return after is not None and after == before
