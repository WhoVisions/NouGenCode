from pathlib import Path

from nougencode.tools import ToolExecutor


def test_write_file_rejects_parent_traversal(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    executor = ToolExecutor(root_dir=workspace)

    result = executor.write_file("../outside.txt", "must not be written")

    assert result.startswith("Error writing file:")
    assert "within the workspace" in result
    assert not target.exists()


def test_write_file_rejects_absolute_path_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    executor = ToolExecutor(root_dir=workspace)

    result = executor.write_file(str(target), "must not be written")

    assert result.startswith("Error writing file:")
    assert "within the workspace" in result
    assert not target.exists()


def test_write_file_rejects_symlink_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "result.txt"
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    executor = ToolExecutor(root_dir=workspace)

    result = executor.write_file("linked/result.txt", "must not be written")

    assert result.startswith("Error writing file:")
    assert "within the workspace" in result
    assert not target.exists()


def test_write_file_accepts_path_inside_workspace(tmp_path: Path):
    executor = ToolExecutor(root_dir=tmp_path)

    result = executor.write_file("nested/result.txt", "safe")

    assert result.startswith("Successfully wrote")
    assert (tmp_path / "nested" / "result.txt").read_text(encoding="utf-8") == "safe"


def test_view_file_rejects_parent_traversal(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    executor = ToolExecutor(root_dir=workspace)

    result = executor.view_file("../secret.txt")

    assert result.startswith("Error reading file:")
    assert "within the workspace" in result
    assert "outside" not in result.replace("within the workspace", "")


def test_view_file_rejects_absolute_path_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("outside", encoding="utf-8")
    executor = ToolExecutor(root_dir=workspace)

    result = executor.view_file(str(secret))

    assert result.startswith("Error reading file:")
    assert "within the workspace" in result


def test_view_file_reads_path_inside_workspace(tmp_path: Path):
    (tmp_path / "inside.txt").write_text("hello", encoding="utf-8")
    executor = ToolExecutor(root_dir=tmp_path)

    assert "hello" in executor.view_file("inside.txt")


def test_edit_file_rejects_parent_traversal(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("original content", encoding="utf-8")
    executor = ToolExecutor(root_dir=workspace)

    result = executor.edit_file("../outside.txt", "original", "modified")

    assert result.startswith("Error editing file:")
    assert "within the workspace" in result
    assert target.read_text(encoding="utf-8") == "original content"


def test_edit_file_rejects_absolute_path_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("original content", encoding="utf-8")
    executor = ToolExecutor(root_dir=workspace)

    result = executor.edit_file(str(target), "original", "modified")

    assert result.startswith("Error editing file:")
    assert "within the workspace" in result
    assert target.read_text(encoding="utf-8") == "original content"


def test_edit_file_rejects_symlink_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("original", encoding="utf-8")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    executor = ToolExecutor(root_dir=workspace)

    result = executor.edit_file("linked/target.txt", "original", "mutated")

    assert result.startswith("Error editing file:")
    assert "within the workspace" in result
    assert target.read_text(encoding="utf-8") == "original"


def test_edit_file_auto_heals_syntax(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text("def hello() -> str:\n    return 'world'\n", encoding="utf-8")
    executor = ToolExecutor(root_dir=tmp_path)

    # Patch with duplicate colons that SyntaxHealer can repair
    result = executor.edit_file("sample.py", "def hello() -> str:", "def hello() -> str::::")

    assert "Successfully patched" in result
    assert "Auto-healed syntax" in result
    assert "def hello() -> str:" in sample.read_text(encoding="utf-8")


def test_edit_file_rejects_corrupted_syntax(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text("def compute(x):\n    return x * 2\n", encoding="utf-8")
    executor = ToolExecutor(root_dir=tmp_path)

    # Patch with broken syntax that cannot be healed
    result = executor.edit_file("sample.py", "return x * 2", "return )(")

    assert "SyntaxError prevented edit" in result
    assert sample.read_text(encoding="utf-8") == "def compute(x):\n    return x * 2\n"


def test_edit_file_patches_successfully(tmp_path: Path):
    sample = tmp_path / "module.txt"
    sample.write_text("alpha beta gamma", encoding="utf-8")
    executor = ToolExecutor(root_dir=tmp_path)

    result = executor.edit_file("module.txt", "beta", "omega")

    assert "Successfully patched 'module.txt' (1 replacement made)" in result
    assert sample.read_text(encoding="utf-8") == "alpha omega gamma"


def test_grep_search_clamps_and_filters(tmp_path: Path):
    (tmp_path / "file1.py").write_text("def special_anchor():\n    pass\n", encoding="utf-8")
    (tmp_path / "file2.py").write_text("x = 1\n", encoding="utf-8")
    executor = ToolExecutor(root_dir=tmp_path)

    result = executor.grep_search("special_anchor")
    assert "file1.py:1: def special_anchor():" in result

    not_found = executor.grep_search("nonexistent_symbol_123")
    assert "No matches found." in not_found
