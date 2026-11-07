"""Unit tests for NouGenCode ElevationEngine."""

from pathlib import Path
import tempfile

from nougencode.elevate import ElevationEngine, ElevationReport


def test_elevation_engine_udct_verification(tmp_path: Path):
    engine = ElevationEngine(tmp_path)
    verified = engine.verify_udct()

    # All 7 target languages must be verified deterministically
    assert len(verified) == 7
    assert "typescript" in verified
    assert "python" in verified
    assert "rust" in verified
    assert "go" in verified
    assert "cpp" in verified
    assert "csharp" in verified
    assert "kotlin" in verified


def test_elevation_engine_audit_invariants(tmp_path: Path):
    # Create clean file and violating file
    (tmp_path / "clean.py").write_text("x = 42\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("leaked = r'C:\\Users\\super\\secret'\n", encoding="utf-8")

    engine = ElevationEngine(tmp_path)
    violations = engine.audit_invariants(auto_repair=False)

    assert len(violations) == 1
    assert violations[0]["file"] == "bad.py"
    assert violations[0]["type"] == "PERSONAL_PATH_LEAK"


def test_elevation_engine_dead_code_scan(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "sample.py").write_text("import os\n\ndef main():\n    print('hi')\n", encoding="utf-8")

    engine = ElevationEngine(tmp_path)
    ast_issues, orphans = engine.scan_dead_code()

    # Should detect unused import 'os' in sample.py
    assert any(i["symbol"] == "os" for i in ast_issues)


def test_elevation_report_formatting_and_lifecycle(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "app.py").write_text("def run():\n    pass\n", encoding="utf-8")

    engine = ElevationEngine(tmp_path)
    report = engine.run_elevation(apply_repairs=False, persist=False)

    assert isinstance(report, ElevationReport)
    assert len(report.udct_languages_verified) == 7
    report_dict = report.to_dict()
    assert "timestamp_utc" in report_dict
    assert "tests_total" in report_dict

    md = report.to_markdown()
    assert "NouGenCode Autonomous Elevation Report" in md
    assert "UDCT Polyglot Engines" in md
