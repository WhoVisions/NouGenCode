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
