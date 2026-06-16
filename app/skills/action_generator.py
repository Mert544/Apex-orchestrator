from __future__ import annotations

import re
from pathlib import Path

from app.models.enums import ClaimType


class ActionGenerator:
    META_PREFIXES = (
        "Missing-information claim:",
        "Contradiction claim:",
        "Deepening claim:",
        "Risk claim:",
        "Investigation claim:",
    )

    PATH_PATTERN = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|yml|yaml|toml|json|ini|cfg|md|txt)")

    # Keyword phrase (matched in the lowercased claim) -> action template.
    # Only consulted when the claim references concrete paths. Order matters:
    # the first matching keyword wins, mirroring the original if-ladder.
    _KEYWORD_TEMPLATES = (
        ("untested module claim", "Prioritize test coverage for the referenced modules: {paths}."),
        ("dependency hub claim", "Review central modules and reduce architectural coupling around: {paths}."),
        ("sensitive surface claim", "Perform a security-focused review for the referenced sensitive paths: {paths}."),
        ("configuration claim", "Audit configuration handling and default safety for: {paths}."),
        ("automation claim", "Tighten CI or workflow enforcement around: {paths}."),
    )

    # claim_type -> action template used when the claim references concrete paths.
    _PATH_TYPE_TEMPLATES = {
        ClaimType.SECURITY: "Review secrets, auth, and payment handling in: {paths}.",
        ClaimType.VALIDATION: "Strengthen or add tests for: {paths}.",
        ClaimType.AUTOMATION: "Expand automated checks for: {paths}.",
        ClaimType.CONFIGURATION: "Harden configuration boundaries around: {paths}.",
        ClaimType.ARCHITECTURE: "Refactor or split high-centrality modules such as: {paths}.",
        ClaimType.OPERATIONS: "Improve observability and failure handling around: {paths}.",
    }

    # claim_type -> action template used as a text fallback when no paths are present.
    _TEXT_TYPE_TEMPLATES = {
        ClaimType.VALIDATION: "Add or strengthen tests for validation-critical behavior implied by: {claim}",
        ClaimType.SECURITY: "Review security-sensitive behavior and harden controls for: {claim}",
        ClaimType.AUTOMATION: "Tighten CI validation gates related to: {claim}",
        ClaimType.CONFIGURATION: "Audit configuration defaults and environment coupling for: {claim}",
        ClaimType.ARCHITECTURE: "Inspect architectural coupling and consider refactoring around: {claim}",
        ClaimType.FEATURE_GAP: "Turn this gap into an engineering task with explicit acceptance criteria: {claim}",
        ClaimType.OPERATIONS: "Evaluate runtime observability and operational safeguards for: {claim}",
    }

    def generate(self, nodes, profile=None) -> list[str]:
        actions: list[str] = []
        seen: set[str] = set()

        for action in self._profile_actions(profile):
            if action not in seen:
                seen.add(action)
                actions.append(action)

        sorted_nodes = sorted(nodes, key=lambda n: n.claim_priority, reverse=True)
        for node in sorted_nodes:
            action = self._action_for_node(node)
            if action and action not in seen:
                seen.add(action)
                actions.append(action)
            if len(actions) >= 10:
                break

        return actions

    def _profile_actions(self, profile) -> list[str]:
        if profile is None:
            return []

        actions: list[str] = []
        if getattr(profile, "critical_untested_modules", None):
            modules = ", ".join(profile.critical_untested_modules[:5])
            actions.append(f"Add or expand tests for critical untested modules: {modules}.")
        if getattr(profile, "sensitive_paths", None):
            paths = ", ".join(profile.sensitive_paths[:5])
            actions.append(f"Run a focused security review on sensitive paths: {paths}.")
        if getattr(profile, "dependency_hubs", None):
            hubs = ", ".join(profile.dependency_hubs[:5])
            actions.append(f"Inspect and reduce coupling in central dependency hubs: {hubs}.")
        if getattr(profile, "config_files", None):
            configs = ", ".join(profile.config_files[:5])
            actions.append(f"Audit configuration surfaces for unsafe defaults and environment coupling: {configs}.")
        if getattr(profile, "ci_files", None):
            ci_files = ", ".join(profile.ci_files[:3])
            actions.append(f"Review CI workflow coverage and strengthen automated gates in: {ci_files}.")
        return actions

    def _action_for_node(self, node) -> str | None:
        claim = node.claim.strip()
        if claim.startswith(self.META_PREFIXES):
            return None

        paths = self._extract_paths(claim)
        claim_type = node.claim_type

        if paths:
            joined = ", ".join(paths[:5])
            template = self._keyword_template(claim.lower()) or self._PATH_TYPE_TEMPLATES.get(claim_type)
            if template is not None:
                return template.format(paths=joined)

        text_template = self._TEXT_TYPE_TEMPLATES.get(claim_type)
        if text_template is not None:
            return text_template.format(claim=claim)
        return None

    def _keyword_template(self, lowered: str) -> str | None:
        for keyword, template in self._KEYWORD_TEMPLATES:
            if keyword in lowered:
                return template
        return None

    def _extract_paths(self, text: str) -> list[str]:
        paths = [m.group(0) for m in self.PATH_PATTERN.finditer(text)]
        cleaned: list[str] = []
        for path in paths:
            normalized = str(Path(path))
            if normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned
