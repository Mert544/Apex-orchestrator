"""Self-registering objective: harden — land a real security fix per finding.

This wires the ALREADY-BUILT 14-patcher security engine
(:mod:`app.execution.semantic.transforms.security`) onto the autonomous develop
surface as a first-class objective. It adds NO new detector and NO new safety
machinery: the findings come from the existing
:func:`app.engine.detectors.security_labels` scan and each fix is produced by the
existing ``security.apply`` patcher set, routed through the SAME
verified-with-rollback engine every other develop move uses.

Two honestly-scoped tiers of "lands working code" (the patcher chooses per label):

* **Tier-0 — ANNOTATE.** For a risk with NO safe automatic rewrite (``pickle.loads``,
  f-string SQL, ``tempfile.mktemp``, ``os.popen``, ``verify=False`` TLS, unguarded
  ``extractall`` Zip-Slip, a weak ``hashlib.md5``/``sha1`` used for security) the
  patcher inserts a reviewable ``# SECURITY (...)`` comment above the call site. The
  source stays byte-identical except for that one added line and re-parses — a
  behaviour-identical, reviewer-facing flag, not a silent behaviour change.
* **Tier-1 — REWRITE.** For a risk with a provably-equivalent safe form the patcher
  rewrites the vulnerability away: ``eval`` → ``ast.literal_eval`` (literal args
  only), ``os.system`` → ``subprocess.run(shlex.split(...), check=True)``,
  ``subprocess(..., shell=True)`` over a metachar-free literal → ``shlex.split`` +
  ``shell=False``, ``except:`` / ``except BaseException:`` → ``except Exception:``,
  ``yaml.load`` → ``yaml.safe_load``, ``hashlib.new("md5")`` →
  ``…, usedforsecurity=False``. Each rewrite stays full-suite-gated, so an
  unexpected behaviour change is caught and auto-rolled-back.

The objective is multi-finding-per-module: a single file can carry several distinct
security labels, and each one is a SEPARATE landable move (mirroring
``dedup_total_return``'s custom-spec shape rather than the single-rewrite
``register_module_objective`` helper). It refuses a test/fixture file and a
non-library script FIRST (the same gate model the broad single-file family uses),
then keeps only the ``(module, label)`` pairs whose guarded plan actually produces a
non-empty rewrite — so the engine's own refusals (a syntax error, an already-flagged
site, a per-patcher safety decline such as a non-literal ``eval`` or a dynamic
``shell=True`` argument) drop out as honest no-ops rather than empty moves.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _content_plan(project_root: str | Path, rel: str, label: str):
    """The guarded SemanticPatchResult→RenamePlan adapter for one (rel, label).

    Imported lazily and bound per move so the plan re-derives against the project's
    CURRENT state when the move runs (line numbers shift as earlier moves land),
    exactly like every other develop objective's ``build_plan`` thunk."""
    from app.engine.objective_compiler import _content_plan as content_plan
    from app.execution.semantic.transforms import security

    return content_plan(project_root, rel, security.apply, label)


def _landable(project_root: str | Path) -> list[tuple[str, str]]:
    """The ``(module, security-label)`` pairs a real, verifiable fix can land.

    For each of the project's own non-fixture modules, for each present security
    label, keep the pair when (a) the file is NOT a test/fixture or a non-library
    script (the same refusal the broad single-file family applies — a fix there is
    fixture/config noise, not a library contribution) and (b) the guarded
    ``_content_plan`` yields a non-empty ``new_contents`` (the engine produced an
    actual rewrite rather than declining). Deterministic: own modules and labels are
    both emitted in a fixed order, no clock/randomness."""
    from app.engine.detectors import security_labels
    from app.engine.objective_compiler import _own_modules
    from app.execution.cross_file_rename import (
        _is_fixture_path,
        _is_non_library_file,
    )

    out: list[tuple[str, str]] = []
    for rel, src in _own_modules(project_root):
        if _is_fixture_path(rel) or _is_non_library_file(rel):
            continue  # test/fixture or packaging/config script — not a library fix
        for label in security_labels(src):
            if _content_plan(project_root, rel, label).new_contents:
                out.append((rel, label))
    return out


def fitness(project_root: str | Path) -> float:
    """Fitness = how many landable security findings remain across own modules.

    Per-``(module, label)`` granularity, so it ticks down one finding at a time and
    reaches 0 when nothing landable is left (mirroring
    ``dedup_total_return.fitness``)."""
    return float(len(_landable(project_root)))


def moves(project_root: str | Path) -> list:
    """One ``harden`` move per landable ``(module, label)`` pair.

    The move carries a ``build_plan`` thunk binding its ``rel``/``label`` so the plan
    re-derives against the current tree when it runs. NO ``scope_verify`` (the move
    stays full-suite-gated → A3-clean) and NO ``apply_rename`` call (the registry's
    sole-gated-writer rule → A1-clean): the move only DESCRIBES the fix; the develop
    loop applies it through the shared verified-with-rollback writer."""
    from app.engine.objective_compiler import Move

    out: list = []
    for rel, label in _landable(project_root):
        out.append(Move(
            operator="harden",
            target=f"{rel}:harden-{label}",
            description=f"fix {label} security finding in {rel}",
            build_plan=lambda r=rel, lb=label: _content_plan(project_root, r, lb),
        ))
    return out


register(ObjectiveSpec(name="harden", fitness=fitness, moves=moves))
