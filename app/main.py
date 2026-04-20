from __future__ import annotations

import os
from pathlib import Path

from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.evidence_mapper import EvidenceMapper
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator
from app.utils.json_utils import pretty_json
from app.utils.yaml_utils import load_yaml


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config = load_yaml(repo_root / "config" / "default.yaml")

    target_root = Path(os.getenv("EPISTEMIC_TARGET_ROOT", str(repo_root))).resolve()
    validator = Validator(evidence_mapper=EvidenceMapper(project_root=target_root))
    decomposer = Decomposer(project_root=target_root)

    orchestrator = FractalResearchOrchestrator(
        config=config,
        decomposer=decomposer,
        validator=validator,
        synthesizer=Synthesizer(project_root=target_root),
    )

    objective = (
        "Scan the target project, extract meaningful implementation claims, "
        "and continue with constitution-driven fractal questioning."
    )
    report = orchestrator.run(objective)
    print(pretty_json(report.model_dump()))


if __name__ == "__main__":
    main()
