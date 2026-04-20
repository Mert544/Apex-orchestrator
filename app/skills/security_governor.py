class SecurityGovernor:
    BLOCKED_PATTERNS = {
        "unsafe_tool",
        "secret_leak",
        "policy_violation",
    }

    def review(self, node) -> float:
        lowered = node.claim.lower()
        if any(pattern in lowered for pattern in self.BLOCKED_PATTERNS):
            return 0.0
        return 0.95
