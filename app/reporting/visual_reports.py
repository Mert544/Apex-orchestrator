from __future__ import annotations

from pathlib import Path
from typing import Any


class VisualReportGenerator:
    """Generate visual reports from run comparisons.

    Features:
    - Markdown summary with ASCII charts
    - Trend visualization
    - Summary statistics

    Usage:
        generator = VisualReportGenerator()
        report = generator.generate_report(comparison.compare_recent())
    """

    def __init__(
        self, project_root: str = ".", output_dir: str = ".apex/reports"
    ) -> None:
        self.project_root = Path(project_root)
        self.output_dir = self.project_root / output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self, comparison_data: dict[str, Any]) -> str:
        """Generate a markdown report from comparison data."""
        if "error" in comparison_data:
            return f"# Error\n\n{comparison_data['error']}"

        report_lines = [
            "# Apex Run Comparison Report",
            "",
            f"**Runs Compared:** {comparison_data.get('runs_compared', 0)}",
            f"**Date Range:** {comparison_data.get('date_range', {}).get('start', 'N/A')} to {comparison_data.get('date_range', {}).get('end', 'N/A')}",
            "",
            "## Summary",
            "",
        ]

        summary = comparison_data.get("summary", {})
        report_lines.extend(
            [
                f"- Avg Duration: {summary.get('avg_duration_seconds', 0):.2f}s",
                f"- Total Patches Applied: {summary.get('total_patches_applied', 0)}",
                f"- Total Patches Blocked: {summary.get('total_patches_blocked', 0)}",
                f"- Test Pass Rate: {summary.get('test_pass_rate', 0):.1f}%",
                f"- Safety Gate Pass Rate: {summary.get('safety_gate_pass_rate', 0):.1f}%",
                "",
            ]
        )

        trend = comparison_data.get("trend", {})
        report_lines.extend(
            [
                "## Trends",
                "",
                f"- Patches: {trend.get('patches', 'N/A')}",
                f"- Tests: {trend.get('tests', 'N/A')}",
                "",
            ]
        )

        report_lines.extend(
            [
                "## Run History",
                "",
                "| Run | Mode | Goal | Patches | Tests | Duration |",
                "|-----|------|------|---------|-------|----------|",
            ]
        )

        for run in comparison_data.get("runs", []):
            run_id = run.get("run_id", "N/A")[:12]
            mode = run.get("mode", "N/A")
            goal = run.get("goal", "N/A")[:20]
            patches = run.get("patches_applied", 0)
            tests = "✓" if run.get("tests_passed") else "✗"
            duration = run.get("duration_seconds", 0)
            report_lines.append(
                f"| {run_id} | {mode} | {goal} | {patches} | {tests} | {duration:.1f}s |"
            )

        report_lines.append("")

        report_lines.extend(self._generate_ascii_chart(comparison_data))

        return "\n".join(report_lines)

    def _generate_ascii_chart(self, data: dict[str, Any]) -> list[str]:
        lines = [
            "",
            "## Activity Chart",
            "",
        ]

        summary = data.get("summary", {})
        total_patches = summary.get("total_patches_applied", 0)
        total_blocked = summary.get("total_patches_blocked", 0)

        if total_patches > 0:
            max_bar = 30
            applied_bar = int(
                (total_patches / max(total_patches + total_blocked, 1)) * max_bar
            )
            blocked_bar = max_bar - applied_bar

            lines.append(
                f"Applied:  {'█' * applied_bar}{'░' * blocked_bar} {total_patches}"
            )
            lines.append(
                f"Blocked: {'░' * applied_bar}{'█' * blocked_bar}{'░' * (max_bar - applied_bar - blocked_bar)} {total_blocked}"
            )

        lines.append("")
        return lines

    def save_report(
        self, comparison_data: dict[str, Any], filename: str | None = None
    ) -> Path:
        """Generate and save report to file."""
        report = self.generate_report(comparison_data)

        if not filename:
            from datetime import datetime

            filename = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"

        output_path = self.output_dir / filename
        output_path.write_text(report, encoding="utf-8")
        return output_path


class ProgressDashboard:
    """Simple progress dashboard for terminal output."""

    def __init__(self) -> None:
        self.width = 50

    def render(self, metrics: dict[str, Any]) -> str:
        lines = [
            "",
            "=" * self.width,
            " APEX PROGRESS DASHBOARD ",
            "=" * self.width,
            "",
        ]

        for key, value in metrics.items():
            if isinstance(value, float):
                lines.append(f"{key:.<30} {value:.2f}")
            else:
                lines.append(f"{key:.<30} {value}")

        lines.append("")
        lines.append("=" * self.width)
        return "\n".join(lines)

    def render_bar(self, label: str, current: int, total: int, width: int = 30) -> str:
        if total == 0:
            return f"{label}: [no data]"

        filled = int((current / total) * width)
        bar = "█" * filled + "░" * (width - filled)
        percent = (current / total) * 100
        return f"{label}: [{bar}] {percent:.1f}% ({current}/{total})"
