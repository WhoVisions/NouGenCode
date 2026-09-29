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