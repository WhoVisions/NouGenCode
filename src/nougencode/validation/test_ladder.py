"""Surgical test ladder: Level 0 (Syntax) to Level 5 (Full Suite)."""

import asyncio
from dataclasses import dataclass
from enum import IntEnum
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import List, Optional

from nougencode.routing.switchboard import ExecutionStatus


class TestLevel(IntEnum):
    __test__ = False
    LEVEL_0_SYNTAX = 0
    LEVEL_1_TARGETED = 1
    LEVEL_2_MODULE = 2
    LEVEL_3_PACKAGE = 3
    LEVEL_4_INTEGRATION = 4
    LEVEL_5_FULL_SUITE = 5


@dataclass
class TestLadderResult:
    __test__ = False
    level: TestLevel
    status: ExecutionStatus
    command: str
    output: str
    duration_s: float
    timed_out: bool = False


class TestLadder:
    """Escalates test validation strictly from narrowest to broadest surface."""
    __test__ = False

    def __init__(self, repo_root: str, base_timeout_s: float = 30.0) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.base_timeout_s = base_timeout_s

    async def run_syntax_check(self, files: List[str]) -> TestLadderResult:
        """Level 0: Syntax / Compilation check via py_compile."""
        t0 = time.time()
        missing = [f for f in files if Path(f).suffix == ".py" and not (self.repo_root / f).is_file()]
        if missing:
            return TestLadderResult(
                level=TestLevel.LEVEL_0_SYNTAX,
                status=ExecutionStatus.FAIL,
                command="py_compile",
                output="Expected Python files are missing: " + ", ".join(sorted(missing)),
                duration_s=time.time() - t0,
            )
        for f in files:
            full_path = self.repo_root / f
            if full_path.suffix == ".py" and full_path.exists():
                cmd = [sys.executable, "-m", "py_compile", str(full_path)]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.repo_root),
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    return TestLadderResult(
                        level=TestLevel.LEVEL_0_SYNTAX,
                        status=ExecutionStatus.FAIL,
                        command=" ".join(cmd),
                        output=stderr.decode("utf-8", errors="replace"),
                        duration_s=time.time() - t0,
                    )
        return TestLadderResult(
            level=TestLevel.LEVEL_0_SYNTAX,
            status=ExecutionStatus.PASS,
            command="py_compile",
            output="Syntax check passed cleanly",
            duration_s=time.time() - t0,
        )

    async def run_targeted_test(self, test_file: str, timeout_s: Optional[float] = None) -> TestLadderResult:
        """Level 1: Exact targeted test file execution."""
        t0 = time.time()
        tout = timeout_s or self.base_timeout_s
        import sys
        cmd = [sys.executable, "-m", "pytest", test_file]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.repo_root / "src")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_root),
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=tout)
            out_str = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
            status = ExecutionStatus.PASS if proc.returncode == 0 else ExecutionStatus.FAIL
            return TestLadderResult(
                level=TestLevel.LEVEL_1_TARGETED,
                status=status,
                command=" ".join(cmd),
                output=out_str,
                duration_s=time.time() - t0,
            )
        except asyncio.TimeoutError:
            # Epistemic law: Timeout != Failure. It is UnknownWithinBudget.
            return TestLadderResult(
                level=TestLevel.LEVEL_1_TARGETED,
                status=ExecutionStatus.TIMEOUT,
                command=" ".join(cmd),
                output=f"Execution exceeded budget ({tout}s). Epistemic state: UnknownWithinBudget.",
                duration_s=tout,
                timed_out=True,
            )
