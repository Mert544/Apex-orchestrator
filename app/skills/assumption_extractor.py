class AssumptionExtractor:
    def extract(self, claim: str) -> list[str]:
        return [
            f"This claim assumes the input data is representative: {claim}",
            f"This claim assumes the evidence collection process is relevant: {claim}",
        ]
