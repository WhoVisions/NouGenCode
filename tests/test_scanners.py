"""Unit tests for NouGenCode AST dead code and orphan scanner."""

import tempfile
from pathlib import Path
from nougencode.scanners.ast_scanner import AstDeadCodeScanner
from nougencode.scanners.orphan_scanner import OrphanFileScanner
from nougencode.scanners.dep_scanner import DependencyScanner
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


def test_ast_submodule_import_and_future_annotations_not_dead():
    scanner = AstDeadCodeScanner()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w+", delete=False, encoding="utf-8") as f:
        code = (
            "from __future__ import annotations\n"
            "import urllib.request\n"
            "import unused_module\n\n"
            "def fetch():\n"
            "    return urllib.request.Request('http://example.com')\n"
        )
        f.write(code)
        f_path = Path(f.name)

    try:
        issues = scanner.scan_file(f_path)
        # Only unused_module should be flagged; annotations and urllib.request should be recognized as used/valid
        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.UNUSED_IMPORT
        assert issues[0].symbol_name == "unused_module"
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


def test_tool_executor_surgical_edit():
    from nougencode.tools import ToolExecutor
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        sample = tmp_path / "sample.py"
        sample.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        executor = ToolExecutor(tmp_path)
        res = executor.edit_file("sample.py", "return 'world'", "return 'nougen'")
        assert "Successfully patched" in res
        assert "return 'nougen'" in sample.read_text(encoding="utf-8")


def test_dependency_scanner_requirements_txt():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        req = tmp_path / "requirements.txt"
        req.write_text("pyyaml>=6.0\npytest\nunused-package==1.0.0\n", encoding="utf-8")

        # Code only imports yaml and pytest
        code = tmp_path / "main.py"
        code.write_text("import yaml\nimport pytest\nprint(yaml.__file__)\n", encoding="utf-8")

        scanner = DependencyScanner(tmp_path)
        issues = scanner.scan_dependencies()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.UNUSED_DEPENDENCY
        assert issues[0].symbol_name == "unused_package"


def test_dependency_scanner_pyproject_toml():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            """[project]
name = "demo-pkg"
version = "0.1.0"
dependencies = [
    "pydantic-settings>=2.0",
    "bloated-lib>=1.0"
]
""",
            encoding="utf-8",
        )

        # Code only imports pydantic_settings
        code = tmp_path / "main.py"
        code.write_text("import pydantic_settings\n", encoding="utf-8")

        scanner = DependencyScanner(tmp_path)
        issues = scanner.scan_dependencies()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.UNUSED_DEPENDENCY
        assert issues[0].symbol_name == "bloated_lib"

