"""Unit tests for NouGenCode Benchmark Engine and Scoreboard."""

from pathlib import Path
from nougencode.bench import BenchmarkEngine, BenchmarkSuite, BenchmarkReport


def test_udct_benchmark_suite():
    engine = BenchmarkEngine()
    results = engine.run_udct_suite()
    assert len(results) == 35  # 5 archetypes x 7 languages
    assert all(r.passed for r in results)
    for r in results:
        assert r.suite == "udct"
        assert r.details["loc"] >= 5
        assert r.details["test_obligations"] > 0
        assert r.duration_ms >= 0


def test_ast_benchmark_suite():
    engine = BenchmarkEngine()
    results = engine.run_ast_suite()
    assert len(results) == 6
    assert all(r.passed for r in results)
    task_names = [r.name for r in results]
    assert "ast::dead_import_single" in task_names
    assert "ast::clean_import_single" in task_names
    assert "ast::submodule_dotted_import" in task_names
    assert "ast::future_compiler_directive" in task_names
    assert "ast::dead_private_func" in task_names
    assert "ast::used_private_func" in task_names


def test_edit_benchmark_suite():
    engine = BenchmarkEngine()
    results = engine.run_edit_suite()
    assert len(results) == 5
    assert all(r.passed for r in results)
    task_names = [r.name for r in results]
    assert "edit::drop_in_replace" in task_names
    assert "edit::syntax_heal_colon" in task_names
    assert "edit::syntax_heal_repeated_colons" in task_names
    assert "edit::sandbox_traversal_rejection" in task_names
    assert "edit::fatal_syntax_rejection" in task_names


def test_benchmark_engine_full_run_and_reporting():
    engine = BenchmarkEngine()
    report = engine.run_benchmarks(suite=BenchmarkSuite.ALL, persist=False)
    assert isinstance(report, BenchmarkReport)
    assert report.total_benchmarks == 35 + 6 + 5  # 46 total benchmarks
    assert report.passed_benchmarks == 46
    assert report.failed_benchmarks == 0
    assert report.pass_rate == 1.0
    assert "udct" in report.suites_run
    assert "ast" in report.suites_run
    assert "edit" in report.suites_run

    md = report.to_markdown()
    assert "# 🏆 NouGenCode Benchmark Scoreboard" in md
    assert "100.0%" in md
    assert "udct::AuthService::typescript" in md

    d = report.to_dict()
    assert d["pass_rate"] == 1.0
    assert len(d["tasks"]) == 46
