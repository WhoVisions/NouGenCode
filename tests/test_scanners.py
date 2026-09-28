"""Unit tests for NouGenCode AST dead code and orphan scanner."""

import tempfile
from pathlib import Path
from nougencode.scanners.ast_scanner import AstDeadCodeScanner
from nougencode.scanners.orphan_scanner import OrphanFileScanner
from nougencode.models import IssueType


def test_ast_dead_import():
    scanner = AstDeadCodeScanner()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w+", delete=False, encoding="utf-8") as f:
        f.write("import os\nimport sys\n\nprint(os.getcwd())\n")
        f_path = Path(f.name)

    try:
        issues = scanner.scan_file(f_path)
        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.UNUSED_IMPORT
        assert issues[0].symbol_name == "sys"
    finally:
        f_path.unlink()


def test_ast_dead_private_func():
    scanner = AstDeadCodeScanner()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w+", delete=False, encoding="utf-8") as f:
        f.write("def _unused_helper():\n    return 42\n\ndef main():\n    print('hello')\n")
        f_path = Path(f.name)

    try:
        issues = scanner.scan_file(f_path)
        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.UNUSED_FUNCTION
        assert issues[0].symbol_name == "_unused_helper"
    finally:
        f_path.unlink()


def test_orphan_scanner():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Create an orphan test script
        orphan = tmp_path / "temp_scratch_test.py"
        orphan.write_text("print('orphan')", encoding="utf-8")

        # Create a main file that imports something else
        main_py = tmp_path / "app.py"
        main_py.write_text("import math\nprint(math.pi)", encoding="utf-8")

        scanner = OrphanFileScanner(tmp_path)
        issues = scanner.scan_orphans()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.ORPHAN_FILE
        assert issues[0].symbol_name == "temp_scratch_test.py"
