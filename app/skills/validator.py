class Validator:
    def validate(self, claim: str) -> dict:
        return {
            "evidence_for": [
                f"Support found for: {claim}",
                f"Secondary supporting angle for: {claim}",
            ],
            "evidence_against": [
                f"Counterpoint found for: {claim}",
            ],
            "assumptions": [
                f"Implicit assumption behind claim: {claim}",
            ],
            "risk": 0.4,
        }
