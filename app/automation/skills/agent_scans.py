from __future__ import annotations

from app.automation.models import AutomationContext
from app.agents.skills import SecurityAgent, DocstringAgent, TestStubAgent, DependencyAgent


def security_scan_skill(context: AutomationContext) -> dict:
    """Run security agent in scan-only mode."""
    agent = SecurityAgent()
    return agent.run(project_root=context.project_root)


def docstring_scan_skill(context: AutomationContext) -> dict:
    """Run docstring agent in scan-only mode."""
    agent = DocstringAgent()
    return agent.run(project_root=context.project_root, patch=False)


def coverage_scan_skill(context: AutomationContext) -> dict:
    """Run test-stub agent in scan-only mode."""
    agent = TestStubAgent()
    return agent.run(project_root=context.project_root, generate=False)


def dependency_scan_skill(context: AutomationContext) -> dict:
    """Run dependency agent in scan-only mode."""
    agent = DependencyAgent()
    return agent.run(project_root=context.project_root)
