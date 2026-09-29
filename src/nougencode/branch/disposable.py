"""
Disposable Worktree & "Bad Idea" Branch Engine.

Allows agents to safely incubate speculative ideas or hazardous refactors in isolated
git worktrees, measure test outcomes, and discard without contaminating main.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass
class DisposableBranchSession:
    branch_name: str
    worktree_path: Path
    base_commit: str
    is_active: bool = True


class DisposableBranchManager:
    """Manages ephemeral git worktrees for zero-risk experimentation."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def create_disposable_branch(
        self,
        idea_name: str,
        base_ref: str = "HEAD",
    ) -> DisposableBranchSession:
        safe_name = f"bad-idea-{int(time.time())}-{idea_name.lower().replace(' ', '-')}"
        worktree_dir = self.repo_root / ".nougen_worktrees" / safe_name
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)

        # Get base commit hash
        base_commit = subprocess.check_output(
            ["git", "rev-parse", base_ref],
            cwd=self.repo_root,
            text=True,
        ).strip()

        # Create worktree
        subprocess.check_call(
            ["git", "worktree", "add", "-b", safe_name, str(worktree_dir), base_ref],
            cwd=self.repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return DisposableBranchSession(
            branch_name=safe_name,
            worktree_path=worktree_dir,
            base_commit=base_commit,
        )

    def discard_disposable_branch(self, session: DisposableBranchSession) -> None:
        """Prune the worktree and delete the experimental branch."""
        if not session.is_active:
            return

        subprocess.call(
            ["git", "worktree", "remove", "--force", str(session.worktree_path)],
            cwd=self.repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        subprocess.call(
            ["git", "branch", "-D", session.branch_name],
            cwd=self.repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        session.is_active = False

    def promote_to_candidate_pr(self, session: DisposableBranchSession, pr_title: str) -> str:
        """Lock the worktree changes and preserve as an elevated feature branch."""
        session.is_active = False
        subprocess.call(
            ["git", "worktree", "remove", str(session.worktree_path)],
            cwd=self.repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return session.branch_name
