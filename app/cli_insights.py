"""Insights command: one deterministic pass over the analyzer suite in
``app/tools/``.

``apex insights`` runs each new stdlib-only analyzer
(type-hint coverage, docstring coverage, complexity, dead code, TODO debt,
test balance, function length, API ergonomics, naming, literal density) on a
single ``--target`` root and prints a combined report — a readable Markdown
section per analyzer (headline number + top offenders) by default, or one JSON
object with ``--json``.

Best-effort and resilient: each analyzer runs inside its own try/except, so a
single failing analyzer is skipped (and noted) without sinking the whole report.
Deterministic and offline — no time, no random, no model in the loop; the order
of analyzers and of every offender list is fixed by the analyzers themselves.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

from app.cli_common import _get_project_root


def _to_dict(result: Any) -> dict[str, Any]:
    """Normalize an analyzer result to a plain dict.

    Prefers an explicit ``to_dict()`` (the analyzers that define one), else
    falls back to :func:`dataclasses.asdict` for the plain dataclasses
    (``DeadCodeReport``, ``NamingAudit``). A non-dataclass mapping is returned
    as-is; anything else is wrapped so the report still renders."""
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        out = to_dict()
        if isinstance(out, dict):
            return out
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return {"value": result}


# Each entry: (section title, callable(root) -> result, headline builder,
# offenders key, offender renderer). The headline builder takes the result dict
# and returns a one-line summary; the offender renderer takes one offender dict
# (or value) and returns a bullet string. Order here IS the report order.
def _ratio_pct(value: Any) -> str:
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "?"


def _offender_module_ratio(o: dict) -> str:
    return f"`{o.get('module', '?')}` — {_ratio_pct(o.get('ratio'))} ({o.get('annotated', 0)}/{o.get('total', 0)})"


def _offender_undocumented(o: dict) -> str:
    kind = o.get("kind", "")
    name = o.get("name") or o.get("symbol") or "?"
    module = o.get("module", "?")
    return f"`{module}` — {kind} `{name}`".rstrip()


def _offender_hotspot(o: dict) -> str:
    name = o.get("name") or o.get("function") or "?"
    module = o.get("module", "?")
    comp = o.get("complexity", o.get("score", "?"))
    return f"`{module}` — `{name}` (complexity {comp})"


def _offender_dead(o: dict) -> str:
    return f"`{o.get('module', '?')}` — {o.get('kind', '')} `{o.get('symbol', '?')}` (line {o.get('line', '?')})"


def _offender_todo(o: dict) -> str:
    marker = o.get("marker", "")
    module = o.get("module") or o.get("file") or "?"
    line = o.get("line", "?")
    text = (o.get("text") or "").strip()
    text = f": {text}" if text else ""
    return f"`{module}`:{line} {marker}{text}"


def _offender_under_tested(o: dict) -> str:
    pkg = o.get("package") or o.get("name") or "?"
    ratio = o.get("ratio")
    suffix = f" ({_ratio_pct(ratio)})" if ratio is not None else ""
    return f"`{pkg}`{suffix}"


def _offender_longest(o: dict) -> str:
    name = o.get("name") or o.get("function") or "?"
    module = o.get("module", "?")
    loc = o.get("loc", o.get("length", "?"))
    return f"`{module}` — `{name}` ({loc} LOC)"


def _offender_ergonomics(o: dict) -> str:
    name = o.get("name") or o.get("function") or "?"
    module = o.get("module", "?")
    reason = o.get("reason") or o.get("smell") or o.get("kind") or ""
    reason = f" — {reason}" if reason else ""
    return f"`{module}` — `{name}`{reason}"


def _offender_naming(o: dict) -> str:
    return f"`{o.get('module', '?')}` — {o.get('kind', '')} `{o.get('name', '?')}`".rstrip()


def _offender_literal(o: dict) -> str:
    literal = o.get("literal") if "literal" in o else o.get("value", "?")
    count = o.get("count", o.get("occurrences", "?"))
    return f"`{literal}` — {count}x"


def _headline_type_hints(d: dict) -> str:
    return (f"{_ratio_pct(d.get('overall_ratio'))} of functions fully annotated "
            f"({d.get('annotated_functions', 0)}/{d.get('total_functions', 0)})")


def _headline_docstrings(d: dict) -> str:
    return (f"{_ratio_pct(d.get('overall_public_ratio'))} public-API docstring coverage "
            f"({d.get('documented_public', 0)}/{d.get('total_public', 0)})")


def _headline_complexity(d: dict) -> str:
    return (f"{d.get('over_threshold', 0)} function(s) over the complexity threshold "
            f"of {d.get('threshold', '?')} (max {d.get('max', 0)}, median {d.get('median', 0)})")


def _headline_dead_code(d: dict) -> str:
    n = d.get("candidate_count", d.get("reported_count", 0))
    return f"{n} unreferenced top-level definition(s) across {d.get('files_scanned', 0)} file(s)"


def _headline_todo(d: dict) -> str:
    by = d.get("by_marker") or {}
    breakdown = ", ".join(f"{k}:{v}" for k, v in sorted(by.items())) if by else ""
    breakdown = f" ({breakdown})" if breakdown else ""
    return f"{d.get('total', 0)} inline debt marker(s){breakdown}"


def _headline_test_balance(d: dict) -> str:
    return (f"test/prod LOC ratio {d.get('loc_ratio', 0)} "
            f"({d.get('test_loc', 0)} test LOC vs {d.get('prod_loc', 0)} prod LOC)")


def _headline_function_length(d: dict) -> str:
    return (f"{d.get('over_threshold', 0)} function(s) over {d.get('threshold', '?')} LOC "
            f"(max {d.get('max', 0)}, median {d.get('median', 0)})")


def _headline_ergonomics(d: dict) -> str:
    return (f"{d.get('long_param_count', 0)} long-param, "
            f"{d.get('boolean_trap_count', 0)} boolean-trap, "
            f"{d.get('positional_overload_count', 0)} positional-overload smell(s) "
            f"across {d.get('functions_analyzed', 0)} function(s)")


def _headline_naming(d: dict) -> str:
    return (f"{len(d.get('violations') or [])} naming violation(s) "
            f"across {d.get('files_scanned', 0)} file(s)")


def _headline_literal(d: dict) -> str:
    return (f"{d.get('total_magic', 0)} magic literal(s) across "
            f"{d.get('files_analyzed', 0)} file(s)")


# Generic headline/offender helpers for analyzers that don't need a bespoke
# summary. ``_headline_list`` reports the size of one offender list; the
# returned closure is deterministic (pure function of the result dict).
def _headline_list(list_key: str, noun: str) -> Callable[[dict], str]:
    def _headline(d: dict) -> str:
        return f"{len(d.get(list_key, []) or [])} {noun}"
    return _headline


# Keys worth surfacing for a generic offender, in display priority order.
_GENERIC_OFFENDER_KEYS = (
    "function", "classname", "name", "symbol", "kind", "call", "reason",
    "depth", "instability", "cohesion", "count", "line",
)


def _offender_generic(o: dict) -> str:
    """Render an arbitrary offender dict: a backticked identifier plus up to
    three salient ``k=v`` pairs drawn from a fixed key list (so the rendering is
    deterministic and independent of dict insertion order)."""
    ident = o.get("module") or o.get("key") or "?"
    parts: list[str] = []
    for k in _GENERIC_OFFENDER_KEYS:
        if k in o and o.get(k) is not None:
            parts.append(f"{k}={o.get(k)}")
        if len(parts) == 3:
            break
    suffix = f" — {', '.join(parts)}" if parts else ""
    return f"`{ident}`{suffix}"


def _analyzers() -> list[tuple[str, str, Callable[[str], Any], Callable[[dict], str],
                               str, Callable[[Any], str]]]:
    """The fixed analyzer registry: (key, title, runner, headline, offenders_key,
    offender_renderer). Imports are local so a single broken analyzer module
    never breaks the whole CLI surface."""
    from app.tools.api_ergonomics import analyze_api_ergonomics
    from app.tools.async_safety import analyze_async_safety
    from app.tools.cohesion_metrics import analyze_cohesion
    from app.tools.comment_quality import analyze_comment_quality
    from app.tools.complexity_profile import analyze_complexity
    from app.tools.config_surface import analyze_config_surface
    from app.tools.coupling_metrics import analyze_coupling
    from app.tools.dead_code_scan import analyze_dead_code
    from app.tools.docstring_coverage import analyze_docstring_coverage
    from app.tools.exception_hygiene import analyze_exception_hygiene
    from app.tools.function_length import analyze_function_length
    from app.tools.global_state import analyze_global_state
    from app.tools.inheritance_depth import analyze_inheritance_depth
    from app.tools.literal_density import analyze_literal_density
    from app.tools.logging_hygiene import analyze_logging_hygiene
    from app.tools.naming_audit import analyze_naming
    from app.tools.return_consistency import analyze_return_consistency
    from app.tools.test_balance import analyze_test_balance
    from app.tools.todo_debt import analyze_todo_debt
    from app.tools.type_hint_coverage import analyze_type_hint_coverage

    return [
        ("type_hint_coverage", "Type-hint coverage", analyze_type_hint_coverage,
         _headline_type_hints, "worst_modules", _offender_module_ratio),
        ("docstring_coverage", "Docstring coverage", analyze_docstring_coverage,
         _headline_docstrings, "undocumented_public", _offender_undocumented),
        ("complexity_profile", "Complexity profile", analyze_complexity,
         _headline_complexity, "hotspots", _offender_hotspot),
        ("dead_code_scan", "Dead code", analyze_dead_code,
         _headline_dead_code, "candidates", _offender_dead),
        ("todo_debt", "TODO debt", analyze_todo_debt,
         _headline_todo, "items", _offender_todo),
        ("test_balance", "Test balance", analyze_test_balance,
         _headline_test_balance, "under_tested_packages", _offender_under_tested),
        ("function_length", "Function length", analyze_function_length,
         _headline_function_length, "longest", _offender_longest),
        ("api_ergonomics", "API ergonomics", analyze_api_ergonomics,
         _headline_ergonomics, "offenders", _offender_ergonomics),
        ("naming_audit", "Naming audit", analyze_naming,
         _headline_naming, "violations", _offender_naming),
        ("literal_density", "Literal density", analyze_literal_density,
         _headline_literal, "repeated", _offender_literal),
        ("coupling_metrics", "Coupling metrics", analyze_coupling,
         _headline_list("most_unstable", "unstable modules"),
         "most_unstable", _offender_generic),
        ("cohesion_metrics", "Cohesion metrics", analyze_cohesion,
         _headline_list("low_cohesion", "low-cohesion classes"),
         "low_cohesion", _offender_generic),
        ("exception_hygiene", "Exception hygiene", analyze_exception_hygiene,
         _headline_list("offenders", "exception smells"),
         "offenders", _offender_generic),
        ("async_safety", "Async safety", analyze_async_safety,
         _headline_list("blocking_calls", "blocking calls in async"),
         "blocking_calls", _offender_generic),
        ("return_consistency", "Return consistency", analyze_return_consistency,
         _headline_list("offenders", "inconsistent returns"),
         "offenders", _offender_generic),
        ("global_state", "Global state", analyze_global_state,
         _headline_list("mutable_globals", "mutable globals"),
         "mutable_globals", _offender_generic),
        ("logging_hygiene", "Logging hygiene", analyze_logging_hygiene,
         _headline_list("offenders", "logging smells"),
         "offenders", _offender_generic),
        ("comment_quality", "Comment quality", analyze_comment_quality,
         _headline_list("commented_out", "commented-out blocks"),
         "commented_out", _offender_generic),
        ("inheritance_depth", "Inheritance depth", analyze_inheritance_depth,
         _headline_list("deep_classes", "deep inheritance chains"),
         "deep_classes", _offender_generic),
        ("config_surface", "Config surface", analyze_config_surface,
         _headline_list("keys", "config keys read"),
         "keys", _offender_generic),
    ]


_TOP_OFFENDERS = 5


def _run_all(root: str) -> list[dict[str, Any]]:
    """Run every analyzer on ``root`` best-effort, in registry order.

    Returns one record per analyzer: ``{key, title, ok, data?, headline?,
    offenders_key, error?}``. A failing analyzer yields ``ok=False`` with the
    error message and is otherwise skipped — never crashes the report."""
    records: list[dict[str, Any]] = []
    for key, title, runner, headline, off_key, off_render in _analyzers():
        record: dict[str, Any] = {"key": key, "title": title,
                                  "offenders_key": off_key}
        try:
            data = _to_dict(runner(root))
            record["ok"] = True
            record["data"] = data
            record["headline"] = headline(data)
            record["_offender_render"] = off_render
        except Exception as exc:  # best-effort: skip a failing analyzer
            record["ok"] = False
            record["error"] = f"{type(exc).__name__}: {exc}"
        records.append(record)
    return records


def _render_markdown(records: list[dict[str, Any]], root: str) -> str:
    """A readable section per analyzer: title, headline, top offenders."""
    lines = ["# Apex insights", "",
             f"Deterministic analyzer sweep of `{root}` — headline metric and "
             "top offenders per analyzer (zero-token, no model in the loop).", ""]
    for rec in records:
        lines.append(f"## {rec['title']}")
        lines.append("")
        if not rec.get("ok"):
            lines.append(f"_skipped — {rec.get('error', 'analyzer failed')}_")
            lines.append("")
            continue
        lines.append(rec["headline"])
        lines.append("")
        offenders = rec["data"].get(rec["offenders_key"]) or []
        render = rec["_offender_render"]
        if offenders:
            for o in offenders[:_TOP_OFFENDERS]:
                try:
                    bullet = render(o) if isinstance(o, dict) else str(o)
                except Exception:
                    bullet = str(o)
                lines.append(f"- {bullet}")
            extra = len(offenders) - _TOP_OFFENDERS
            if extra > 0:
                lines.append(f"- _…and {extra} more_")
        else:
            lines.append("_no offenders found_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _json_payload(records: list[dict[str, Any]], root: str) -> dict[str, Any]:
    """One JSON object: ``{root, analyzers: {key: data | {error}}}`` — every
    analyzer's full result keyed by name, with failures captured rather than
    dropped, so the shape is stable across runs."""
    analyzers: dict[str, Any] = {}
    for rec in records:
        if rec.get("ok"):
            analyzers[rec["key"]] = rec["data"]
        else:
            analyzers[rec["key"]] = {"error": rec.get("error", "analyzer failed")}
    return {"root": root, "analyzers": analyzers}


def cmd_insights(args: argparse.Namespace) -> int:
    """Run the whole deterministic analyzer suite on ``--target`` and print one
    combined report (Markdown by default, ``--json`` for the raw object)."""
    target = Path(args.target).resolve() if getattr(args, "target", "") else _get_project_root()
    root = str(target)
    records = _run_all(root)
    if getattr(args, "json", False):
        print(json.dumps(_json_payload(records, root), indent=2))
    else:
        print(_render_markdown(records, root))
    return 0


def register_parsers(subparsers) -> None:
    """Register the ``insights`` subcommand."""
    insights_parser = subparsers.add_parser(
        "insights",
        help="Run the deterministic analyzer suite (type hints, docstrings, "
             "complexity, dead code, TODO debt, test balance, function length, "
             "API ergonomics, naming, literal density) and print a combined report",
    )
    insights_parser.add_argument("--target", default="", help="Target project root")
    insights_parser.add_argument("--json", action="store_true",
                                 help="Emit all analyzer results as one JSON object")
    insights_parser.set_defaults(func=cmd_insights)
