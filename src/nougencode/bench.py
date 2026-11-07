"""Autonomous Benchmark Engine for NouGenCode.

Executes standardized verification benchmarks across:
1. UDCT Polyglot Code Synthesis (7 languages x 5 problem archetypes = 35 tasks)
2. AST Dead Code & Import Detection Precision (6 curated vectors)
3. Surgical Patch & Syntax Healing Precision (5 mutation & security vectors)
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .context_gate import ContextGate
from .scanners.ast_scanner import AstDeadCodeScanner
from .tools import ToolExecutor
from .udct_code import (
    CodeCalculationEngine,
    DeterministicCodeRenderer,
    FrameworkType,
    NormalizedSpec,
    ProjectType,
    TargetLanguage,
)


class BenchmarkSuite(str, Enum):
    UDCT = "udct"
    AST = "ast"
    EDIT = "edit"
    ALL = "all"


@dataclass
class BenchmarkTaskResult:
    suite: str
    name: str
    passed: bool
    duration_ms: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkReport:
    timestamp_utc: str
    suites_run: List[str]
    total_benchmarks: int
    passed_benchmarks: int
    failed_benchmarks: int
    pass_rate: float
    duration_ms: float
    tasks: List[BenchmarkTaskResult] = field(default_factory=list)
    shard_captured: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        status_emoji = "🏆" if self.failed_benchmarks == 0 else "⚠️"
        lines = [
            f"# {status_emoji} NouGenCode Benchmark Scoreboard",
            f"**Timestamp (UTC)**: `{self.timestamp_utc}` | **Suites**: `{', '.join(self.suites_run)}`",
            f"**Pass Rate**: `{self.pass_rate:.1%}` ({self.passed_benchmarks}/{self.total_benchmarks} passed) | **Duration**: `{self.duration_ms:.1f}ms`",
            "",
            "## 📊 Suite Breakdown",
            "| Suite | Tasks | Passed | Failed | Mean Latency |",
            "|---|---|---|---|---|",
        ]

        # Group by suite
        by_suite: Dict[str, List[BenchmarkTaskResult]] = {}
        for t in self.tasks:
            by_suite.setdefault(t.suite, []).append(t)

        for s_name, t_list in by_suite.items():
            s_pass = sum(1 for t in t_list if t.passed)
            s_fail = len(t_list) - s_pass
            mean_lat = sum(t.duration_ms for t in t_list) / max(1, len(t_list))
            lines.append(f"| `{s_name}` | {len(t_list)} | {s_pass} | {s_fail} | {mean_lat:.1f}ms |")

        lines.extend([
            "",
            "## 🔍 Task Details",
            "| Task Name | Suite | Status | Latency | Result Note |",
            "|---|---|---|---|---|",
        ])
        for t in self.tasks:
            st = "✅ PASS" if t.passed else "❌ FAIL"
            lines.append(f"| `{t.name}` | `{t.suite}` | {st} | {t.duration_ms:.1f}ms | {t.message} |")

        return "\n".join(lines)


class BenchmarkEngine:
    """Executes deterministic verification benchmarks across NouGenCode."""

    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = repo_root or Path.cwd()
        self.context_gate = ContextGate(self.repo_root)

    def run_udct_suite(self) -> List[BenchmarkTaskResult]:
        """Runs UDCT code synthesis across 5 archetypes and all 7 target languages."""
        results: List[BenchmarkTaskResult] = []
        archetypes = [
            ("AuthService", ["Session", "Credential"], ["create", "read"]),
            ("PaymentLedger", ["LedgerEntry", "Account"], ["create", "read", "update"]),
            ("InventoryCache", ["Item", "Warehouse"], ["create", "read"]),
            ("TaskScheduler", ["Job", "Trigger"], ["create", "read", "update"]),
            ("EventStream", ["MessageEnvelope", "Consumer"], ["create", "read", "delete"]),
        ]
        languages = [
            TargetLanguage.TYPESCRIPT,
            TargetLanguage.PYTHON,
            TargetLanguage.RUST,
            TargetLanguage.GO,
            TargetLanguage.CPP,
            TargetLanguage.CSHARP,
            TargetLanguage.KOTLIN,
        ]

        for arch_name, entities, capabilities in archetypes:
            for lang in languages:
                task_name = f"udct::{arch_name}::{lang.value}"
                t0 = time.perf_counter()
                try:
                    spec = NormalizedSpec(
                        project_name=f"{arch_name}_{lang.value}",
                        project_type=ProjectType.API_SERVICE,
                        framework=FrameworkType.FASTAPI if lang == TargetLanguage.PYTHON else FrameworkType.NONE,
                        language=lang,
                        entities=entities,
                        capabilities=capabilities,
                    )
                    ir = CodeCalculationEngine.solve_project_ir(spec)
                    code = DeterministicCodeRenderer.render_service_file(entities[0], ir.functions, lang)
                    dur = (time.perf_counter() - t0) * 1000.0

                    line_count = len(code.splitlines())
                    has_tests = ir.total_test_obligations_count > 0
                    passed = (line_count >= 5) and has_tests

                    msg = f"Generated {line_count} LOC, test ladder N={ir.total_test_obligations_count}" if passed else "Generation incomplete or missing test obligations"
                    results.append(
                        BenchmarkTaskResult(
                            suite="udct",
                            name=task_name,
                            passed=passed,
                            duration_ms=round(dur, 2),
                            message=msg,
                            details={"loc": line_count, "test_obligations": ir.total_test_obligations_count, "lang": lang.value},
                        )
                    )
                except Exception as e:
                    dur = (time.perf_counter() - t0) * 1000.0
                    results.append(
                        BenchmarkTaskResult(
                            suite="udct",
                            name=task_name,
                            passed=False,
                            duration_ms=round(dur, 2),
                            message=f"Exception: {e}",
                        )
                    )
        return results

    def run_ast_suite(self) -> List[BenchmarkTaskResult]:
        """Tests AST DeadCode detection precision and recall across curated vectors."""
        results: List[BenchmarkTaskResult] = []
        scanner = AstDeadCodeScanner()

        vectors = [
            ("dead_import_single", "import sys\nimport os\nprint(os.getcwd())\n", {"sys"}, True),
            ("clean_import_single", "import math\nprint(math.pi)\n", set(), True),
            ("submodule_dotted_import", "import urllib.request\nreq = urllib.request.Request('http://a.com')\n", set(), True),
            ("future_compiler_directive", "from __future__ import annotations\nimport os\nprint(os.name)\n", set(), True),
            ("dead_private_func", "def _unused(): pass\ndef main(): pass\n", {"_unused"}, True),
            ("used_private_func", "def _helper(): return 1\ndef main(): return _helper()\n", set(), True),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for vec_name, code, expected_symbols, expected_pass in vectors:
                f_path = tmp_path / f"{vec_name}.py"
                f_path.write_text(code, encoding="utf-8")
                t0 = time.perf_counter()
                try:
                    issues = scanner.scan_file(f_path)
                    dur = (time.perf_counter() - t0) * 1000.0
                    flagged = {i.symbol_name for i in issues}
                    passed = (flagged == expected_symbols)

                    results.append(
                        BenchmarkTaskResult(
                            suite="ast",
                            name=f"ast::{vec_name}",
                            passed=passed,
                            duration_ms=round(dur, 2),
                            message=f"Flagged symbols: {sorted(flagged)} (expected: {sorted(expected_symbols)})",
                            details={"expected": sorted(expected_symbols), "actual": sorted(flagged)},
                        )
                    )
                except Exception as e:
                    dur = (time.perf_counter() - t0) * 1000.0
                    results.append(
                        BenchmarkTaskResult(
                            suite="ast",
                            name=f"ast::{vec_name}",
                            passed=False,
                            duration_ms=round(dur, 2),
                            message=f"Scanner exception: {e}",
                        )
                    )
        return results

    def run_edit_suite(self) -> List[BenchmarkTaskResult]:
        """Tests surgical patching precision, boundary protection, and syntax healing."""
        results: List[BenchmarkTaskResult] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            executor = ToolExecutor(tmp_path)

            # Task 1: Clean drop-in replacement
            t0 = time.perf_counter()
            f1 = tmp_path / "module_clean.py"
            f1.write_text("def solve():\n    return 10\n", encoding="utf-8")
            res1 = executor.edit_file("module_clean.py", "return 10", "return 42")
            dur1 = (time.perf_counter() - t0) * 1000.0
            p1 = "Successfully patched" in res1 and "return 42" in f1.read_text(encoding="utf-8")
            results.append(BenchmarkTaskResult(suite="edit", name="edit::drop_in_replace", passed=p1, duration_ms=round(dur1, 2), message=res1))

            # Task 2: Syntax healing of missing control structure colons
            t0 = time.perf_counter()
            f2 = tmp_path / "module_heal_colon.py"
            f2.write_text("def run():\n    pass\n", encoding="utf-8")
            # Attempt to patch with a missing colon: if condition
            res2 = executor.edit_file("module_heal_colon.py", "pass", "if True\n        pass")
            dur2 = (time.perf_counter() - t0) * 1000.0
            content2 = f2.read_text(encoding="utf-8")
            p2 = "if True:" in content2 and "Auto-healed syntax" in res2
            results.append(BenchmarkTaskResult(suite="edit", name="edit::syntax_heal_colon", passed=p2, duration_ms=round(dur2, 2), message="Auto-repaired missing colon"))

            # Task 3: Syntax healing of corrupted repeated colons
            t0 = time.perf_counter()
            f3 = tmp_path / "module_corrupt_colon.py"
            f3.write_text("def execute():\n    pass\n", encoding="utf-8")
            res3 = executor.edit_file("module_corrupt_colon.py", "pass", "while True::::\n        break")
            dur3 = (time.perf_counter() - t0) * 1000.0
            content3 = f3.read_text(encoding="utf-8")
            p3 = "while True:" in content3 and "Auto-healed syntax" in res3
            results.append(BenchmarkTaskResult(suite="edit", name="edit::syntax_heal_repeated_colons", passed=p3, duration_ms=round(dur3, 2), message="Auto-repaired repeated colons"))

            # Task 4: Rejection of path traversal outside workspace
            t0 = time.perf_counter()
            res4 = executor.edit_file("../../escape.py", "old", "new")
            dur4 = (time.perf_counter() - t0) * 1000.0
            p4 = "must remain within the workspace" in res4
            results.append(BenchmarkTaskResult(suite="edit", name="edit::sandbox_traversal_rejection", passed=p4, duration_ms=round(dur4, 2), message="Blocked sandbox escape"))

            # Task 5: Rejection of unhealable fatal syntax
            t0 = time.perf_counter()
            f5 = tmp_path / "module_fatal.py"
            f5.write_text("def test():\n    pass\n", encoding="utf-8")
            res5 = executor.edit_file("module_fatal.py", "pass", "def invalid syntax {{{]]")
            dur5 = (time.perf_counter() - t0) * 1000.0
            p5 = "SyntaxError prevented edit" in res5 and "pass" in f5.read_text(encoding="utf-8")
            results.append(BenchmarkTaskResult(suite="edit", name="edit::fatal_syntax_rejection", passed=p5, duration_ms=round(dur5, 2), message="Prevented file corruption on fatal syntax"))

        return results

    def persist_shard(self, report: BenchmarkReport) -> bool:
        """Persists benchmark scoreboard to NouGen Shards and Context Gate."""
        self.context_gate.log_event(
            "nougencode_benchmark",
            f"Benchmark pass rate {report.pass_rate:.1%} ({report.passed_benchmarks}/{report.total_benchmarks}) in {report.duration_ms:.1f}ms",
            report.to_dict(),
        )
        try:
            import json
            from nougen_shards.core import capture
            return capture(
                event_type="nougencode_benchmark",
                title=f"NouGenCode Benchmark Scoreboard: {report.pass_rate:.1%}",
                content=json.dumps(report.to_dict(), indent=2),
                tags=["nougencode", "benchmark", "udct", "ast", "edit"],
                domain_key="nougencode_benchmark",
                source_uri="repo://NouGenCode",
            )
        except Exception:
            return False

    def run_benchmarks(self, suite: BenchmarkSuite = BenchmarkSuite.ALL, persist: bool = True) -> BenchmarkReport:
        """Executes selected benchmark suite and produces a comprehensive report."""
        t_start = time.perf_counter()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tasks: List[BenchmarkTaskResult] = []
        suites_run: List[str] = []

        if suite in (BenchmarkSuite.UDCT, BenchmarkSuite.ALL):
            suites_run.append("udct")
            tasks.extend(self.run_udct_suite())

        if suite in (BenchmarkSuite.AST, BenchmarkSuite.ALL):
            suites_run.append("ast")
            tasks.extend(self.run_ast_suite())

        if suite in (BenchmarkSuite.EDIT, BenchmarkSuite.ALL):
            suites_run.append("edit")
            tasks.extend(self.run_edit_suite())

        total_dur = (time.perf_counter() - t_start) * 1000.0
        total = len(tasks)
        passed = sum(1 for t in tasks if t.passed)
        failed = total - passed
        pass_rate = (passed / total) if total > 0 else 0.0

        report = BenchmarkReport(
            timestamp_utc=ts,
            suites_run=suites_run,
            total_benchmarks=total,
            passed_benchmarks=passed,
            failed_benchmarks=failed,
            pass_rate=pass_rate,
            duration_ms=round(total_dur, 2),
            tasks=tasks,
        )

        if persist:
            report.shard_captured = self.persist_shard(report)

        return report
