from __future__ import annotations

from app.models.enums import ClaimType


class ActionGenerator:
    def generate(self, nodes) -> list[str]:
        actions: list[str] = []
        seen: set[str] = set()

        sorted_nodes = sorted(nodes, key=lambda n: n.claim_priority, reverse=True)
        for node in sorted_nodes:
            action = self._action_for_node(node)
            if action and action not in seen:
                seen.add(action)
                actions.append(action)
            if len(actions) >= 10:
                break

        return actions

    def _action_for_node(self, node) -> str | None:
        claim_type = node.claim_type
        claim = node.claim

        if claim_type == ClaimType.SECURITY:
            return f"Review security-sensitive surfaces and harden secrets, auth, or payment handling around: {claim}"
        if claim_type == ClaimType.VALIDATION:
            return f"Add or strengthen tests for validation-critical behavior implied by: {claim}"
        if claim_type == ClaimType.AUTOMATION:
            return f"Add or tighten CI validation gates and workflow checks related to: {claim}"
        if claim_type == ClaimType.CONFIGURATION:
            return f"Audit configuration defaults, environment coupling, and safety checks for: {claim}"
        if claim_type == ClaimType.ARCHITECTURE:
            return f"Inspect architectural coupling and consider refactoring high-centrality modules highlighted by: {claim}"
        if claim_type == ClaimType.FEATURE_GAP:
            return f"Turn this gap into an engineering task and define acceptance criteria for: {claim}"
        if claim_type == ClaimType.OPERATIONS:
            return f"Evaluate runtime observability, failure handling, and operational safeguards for: {claim}"

        lowered = claim.lower()
        if "untested module claim" in lowered:
            return f"Prioritize tests for the modules named in: {claim}"
        if "dependency hub claim" in lowered:
            return f"Review central dependency hubs first and reduce coupling where needed for: {claim}"
        if "sensitive surface claim" in lowered:
            return f"Perform a focused security review on sensitive paths referenced in: {claim}"
        return None
