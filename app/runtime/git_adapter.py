from __future__ import annotations

from pathlib import Path

from app.runtime.command_runner import CommandResult, CommandRunner, CommandSpec


class GitAdapter:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def clone(self, repo_url: str, destination: str | Path, branch: str | None = None, depth: int = 1) -> CommandResult:
        command = ["git", "clone", "--depth", str(depth)]
        if branch:
            command.extend(["--branch", branch])
        command.extend([repo_url, str(Path(destination))])
        return self.runner.run(CommandSpec(command=command))

    def status(self, repo_dir: str | Path) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "status", "--short"], cwd=Path(repo_dir)))

    def diff(self, repo_dir: str | Path, paths: list[str] | None = None) -> CommandResult:
        command = ["git", "diff", "--", *(paths or [])]
        return self.runner.run(CommandSpec(command=command, cwd=Path(repo_dir)))

    def create_branch(self, repo_dir: str | Path, branch_name: str) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "checkout", "-b", branch_name], cwd=Path(repo_dir)))

    def restore(self, repo_dir: str | Path, paths: list[str]) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "restore", "--", *paths], cwd=Path(repo_dir)))

    def current_branch(self, repo_dir: str | Path) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "branch", "--show-current"], cwd=Path(repo_dir)))

    def diff_stat(self, repo_dir: str | Path) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "diff", "--stat"], cwd=Path(repo_dir)))

    def log_oneline(self, repo_dir: str | Path, count: int = 5) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "log", "--oneline", f"-{count}"], cwd=Path(repo_dir)))

    def add(self, repo_dir: str | Path, paths: list[str]) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "add", "--", *paths], cwd=Path(repo_dir)))

    def commit(self, repo_dir: str | Path, message: str) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "commit", "-m", message], cwd=Path(repo_dir)))

    def push(self, repo_dir: str | Path, remote: str = "origin", branch: str | None = None) -> CommandResult:
        command = ["git", "push", remote]
        if branch:
            command.append(branch)
        return self.runner.run(CommandSpec(command=command, cwd=Path(repo_dir)))

    def tag(self, repo_dir: str | Path, tag_name: str, message: str | None = None) -> CommandResult:
        command = ["git", "tag", "-a", tag_name] if message else ["git", "tag", tag_name]
        if message:
            command.extend(["-m", message])
        return self.runner.run(CommandSpec(command=command, cwd=Path(repo_dir)))

    def remote_add(self, repo_dir: str | Path, name: str, url: str) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "remote", "add", name, url], cwd=Path(repo_dir)))

    def remote_list(self, repo_dir: str | Path) -> CommandResult:
        return self.runner.run(CommandSpec(command=["git", "remote", "-v"], cwd=Path(repo_dir)))

    def stash(self, repo_dir: str | Path, message: str | None = None) -> CommandResult:
        command = ["git", "stash", "push"]
        if message:
            command.extend(["-m", message])
        return self.runner.run(CommandSpec(command=command, cwd=Path(repo_dir)))
