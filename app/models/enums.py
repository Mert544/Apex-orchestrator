from enum import Enum


class QuestionType(str, Enum):
    MISSING = "missing"
    CONTRADICTION = "contradiction"
    RISK = "risk"
    DEEPENING = "deepening"


class ClaimType(str, Enum):
    ARCHITECTURE = "architecture"
    VALIDATION = "validation"
    SECURITY = "security"
    CONFIGURATION = "configuration"
    AUTOMATION = "automation"
    FEATURE_GAP = "feature_gap"
    OPERATIONS = "operations"
    GENERAL = "general"


class NodeStatus(str, Enum):
    NEW = "new"
    VALIDATED = "validated"
    EXPANDED = "expanded"
    STOPPED = "stopped"


class StopReason(str, Enum):
    LOW_NOVELTY = "low_novelty"
    LOW_QUALITY = "low_quality"
    LOW_SECURITY = "low_security"
    MAX_DEPTH = "max_depth"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DUPLICATE_BRANCH = "duplicate_branch"
    NO_HIGH_VALUE_QUESTIONS = "no_high_value_questions"
    TIMEOUT = "timeout"
