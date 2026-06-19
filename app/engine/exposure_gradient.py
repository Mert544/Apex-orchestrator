"""Coverage-gradient exposure — which modules are most dangerous to change.

DISCOVERY's sharpest question is not "what is wrong?" but "where is a change
most likely to *hurt*?". A module is dangerous to change in exact proportion to
three independent, already-measured pressures fused here (no new scan):

  * **fan-in** — how many modules import it (its blast radius): a regression
    here ripples to every dependent. Read from ``profile.module_fanin``
    (in-degree), the SAME measure ``blast_radius``/``fragile_modules`` use.
  * **coverage depth** — how strongly the suite vouches for it, on the
    ``verification_strength`` ladder (``function`` > ``module`` > ``none``)
    mapped to a depth in ``[0,1]``. Thin coverage = a green suite proves little
    about a change here.
  * **churn** — how often recent commits touch it. Read from
    ``profile.churn_hotspots`` (commit counts), a deterministic git tally. A
    file under active change is one about to be changed again.

Per module:

    exposure = norm(fanin) * (1 - coverage_depth) * norm(churn)

``norm(x)`` divides by the max in the set (guarded against div-by-zero), so the
score is a unitless ``[0,1]`` blend: it peaks only when a module is a hub AND
thinly covered AND actively churned at once. A leaf, a well-tested module, or a
quiescent one scores 0 on at least one factor and so drops out.

Deterministic (every input is already deterministic; no clock/random; sorted by
``(-exposure, module)`` and capped), stdlib-only, and READ-ONLY — it reads the
profile and writes nothing.
"""

from __future__ import annotations

from app.tools.project_profile import ProjectProfile

__all__ = [
    "COVERAGE_DEPTH",
    "exposure_gradient",
    "render_exposure_gradient_markdown",
]

# Coverage levels on the verification_strength ladder, mapped to a depth in
# [0,1]. ``none`` (applied blind) is the most dangerous, ``function`` (a test
# names the changed function) the safest. The exposure formula multiplies by
# ``(1 - depth)`` so an untested hub keeps its full danger weight while a
# function-covered module is neutralised.
COVERAGE_DEPTH = {"none": 0.0, "module": 0.5, "function": 1.0}

# Default number of exposure leads returned — small on purpose so the signal
# stays a focused "lead with these" list, not a flood.
_DEFAULT_TOP = 5


def _coverage_level(profile: ProjectProfile, module: str) -> str:
    """The verification-strength level of ``module``, from existing profile signals.

    No new scan: the profile already classifies coverage. A module the profiler
    named as untested (or an untested hub) is ``none``; one named as only
    shallow-tested is ``module`` (tests reference it but assert no behaviour);
    a module with at least one linked test is ``function``; one the profiler
    never mentioned at all is treated as ``module`` (covered-enough — it tripped
    no thin-coverage signal). Deterministic: a pure set/dict membership test.
    """
    untested = set(getattr(profile, "untested_modules", []) or [])
    untested |= set(getattr(profile, "critical_untested_modules", []) or [])
    for hub in getattr(profile, "hub_untested_modules", []) or []:
        mod = hub.get("module") if isinstance(hub, dict) else None
        if mod:
            untested.add(mod)
    if module in untested:
        return "none"
    if module in set(getattr(profile, "shallow_tested_modules", []) or []):
        return "module"
    tests = (getattr(profile, "module_to_tests", {}) or {}).get(module)
    if tests:
        return "function"
    # Unmentioned by every thin-coverage signal: not dangerous on the coverage
    # axis, so treat as the neutral middle (its (1-depth) factor is 0.5, not 1).
    return "module"


def _churn_by_module(profile: ProjectProfile) -> dict[str, int]:
    """``module -> recent commit count`` from the profile's churn tally."""
    out: dict[str, int] = {}
    for entry in getattr(profile, "churn_hotspots", []) or []:
        if not isinstance(entry, dict):
            continue
        module = entry.get("module")
        commits = entry.get("commits", 0)
        if module:
            out[module] = int(commits or 0)
    return out


def _norm(value: float, peak: float) -> float:
    """``value / peak`` in [0,1], guarded against a zero/negative peak.

    The div-by-zero guard: when every candidate scores 0 on this axis (peak 0),
    the normalized value is 0 for all of them rather than a ZeroDivisionError —
    so the whole exposure product collapses to 0 and the module drops out, which
    is exactly right (no spread on an axis means it discriminates nothing).
    """
    if peak <= 0:
        return 0.0
    return value / peak


def exposure_gradient(
    profile: ProjectProfile,
    root: str | None = None,
    top: int = _DEFAULT_TOP,
) -> list[dict]:
    """Rank modules by coverage-gradient exposure (most dangerous to change first).

    Fuses three existing, deterministic engines (no reimplementation):

      * fan-in / blast radius — ``profile.module_fanin`` (in-degree),
      * coverage depth — the ``verification_strength`` ladder via
        :func:`_coverage_level` mapped through :data:`COVERAGE_DEPTH`,
      * churn — ``profile.churn_hotspots`` commit counts.

    For each candidate module (the union of the three signals' modules) computes
    ``exposure = norm(fanin) * (1 - coverage_depth) * norm(churn)`` where
    ``norm`` divides by the per-axis maximum (div-by-zero guarded). Returns the
    leads with ``exposure > 0``, sorted by ``(-exposure, module)`` and capped at
    ``top``. Each lead is a dict::

        {"module", "exposure", "fanin", "coverage", "churn", "why"}

    ``root`` is accepted for signature parity with the other analyzers and to
    let callers pass it through; this analysis reads only the (already
    root-derived) profile, so it is unused here and the function stays hermetic.
    READ-ONLY and byte-deterministic.
    """
    fanin = {
        m: int(v or 0)
        for m, v in (getattr(profile, "module_fanin", {}) or {}).items()
    }
    churn = _churn_by_module(profile)

    # Candidate set: any module named by fan-in OR churn. Coverage alone never
    # nominates a module (a thinly-covered leaf with no fan-in and no churn is
    # not dangerous to change — nothing depends on it and nothing is changing
    # it), which keeps the signal pointed at the genuinely risky places.
    candidates = sorted(set(fanin) | set(churn))
    if not candidates:
        return []

    fanin_peak = max((fanin.get(m, 0) for m in candidates), default=0)
    churn_peak = max((churn.get(m, 0) for m in candidates), default=0)

    leads: list[dict] = []
    for module in candidates:
        fi = fanin.get(module, 0)
        ch = churn.get(module, 0)
        level = _coverage_level(profile, module)
        depth = COVERAGE_DEPTH[level]
        exposure = _norm(fi, fanin_peak) * (1.0 - depth) * _norm(ch, churn_peak)
        if exposure <= 0:
            continue
        leads.append({
            "module": module,
            "exposure": round(exposure, 4),
            "fanin": fi,
            "coverage": level,
            "churn": ch,
            "why": (f"fan-in {fi}, coverage {level}, churn {ch} commits "
                    f"(rising)"),
        })

    leads.sort(key=lambda lead: (-lead["exposure"], lead["module"]))
    return leads[: max(0, int(top))]


def render_exposure_gradient_markdown(leads: list[dict]) -> str:
    """Human-readable table of the exposure leads (most dangerous first)."""
    lines = ["# Coverage-gradient exposure", ""]
    if not leads:
        lines.append("_No exposed modules (no hub is both thinly covered and churned)._")
        return "\n".join(lines) + "\n"
    lines.append("| Module | Exposure | Fan-in | Coverage | Churn |")
    lines.append("| --- | --- | --- | --- | --- |")
    for lead in leads:
        lines.append(
            f"| `{lead['module']}` | {lead['exposure']:.4f} | {lead['fanin']} "
            f"| {lead['coverage']} | {lead['churn']} |"
        )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
