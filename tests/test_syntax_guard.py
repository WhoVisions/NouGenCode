"""Tests for SyntaxHealer and syntax auto-fix hook in NouGenCode."""

import ast
import pytest
from nougencode.fabric.syntax_guard import SyntaxHealer, syntax_auto_fix_tool_hook
from nougencode.fabric.hook_abi import HookContext, HookPhase
from nougencode.tools import ToolExecutor


def test_syntax_healer_already_valid():
    code = "def valid_func(x: int) -> int:\n    return x + 1\n"
    res = SyntaxHealer.heal(code)
    assert not res.was_corrupt
    assert not res.repaired
    assert res.healed_code == code


def test_syntax_healer_missing_colons():
    broken = """def calculate_total(a, b)
    if a > b
        return a
    else
        return b
"""
    res = SyntaxHealer.heal(broken)
    assert res.was_corrupt
    assert res.repaired
    # AST must parse cleanly now
    tree = ast.parse(res.healed_code)
    assert len(tree.body) == 1
    assert any("missing colon" in r for r in res.repairs_applied)


def test_syntax_healer_colon_corruption():
    corrupted = "def parse_data(raw: str):::::\n    return raw.strip()\n"
    res = SyntaxHealer.heal(corrupted)
    assert res.was_corrupt
    assert res.repaired
    assert "def parse_data(raw: str):" in res.healed_code
    ast.parse(res.healed_code)


def test_syntax_healer_unclosed_parentheses():
    broken = "x = [1, 2, 3\n"
    res = SyntaxHealer.heal(broken)
    assert res.was_corrupt
    assert res.repaired
    assert res.healed_code.strip() == "x = [1, 2, 3]"
    ast.parse(res.healed_code)


def test_syntax_auto_fix_tool_hook_interception():
    broken_code = "def handler()\n    return True\n"
    ctx = HookContext(
        phase=HookPhase.BEFORE_TOOL_EXECUTION,
        session_id="sess_123",
        task_id="task_123",
        timestamp="2026-09-29T00:00:00Z",
        payload={
            "tool_name": "write_file",
            "args": {"file_path": "service.py", "content": broken_code},
        },
    )

    success, mut_payload, err, abort = syntax_auto_fix_tool_hook(ctx)
    assert success
    assert not abort
    assert mut_payload is not None
    assert mut_payload["syntax_auto_healed"] is True
    assert "def handler():" in mut_payload["args"]["content"]
    ast.parse(mut_payload["args"]["content"])


def test_tool_executor_write_file_auto_heals(tmp_path):
    executor = ToolExecutor(root_dir=tmp_path)
    broken_script = "def run_worker()\n    return 42\n"
    
    msg = executor.write_file("worker.py", broken_script)
    assert "Successfully wrote" in msg
    assert "Auto-healed syntax" in msg

    written_code = (tmp_path / "worker.py").read_text(encoding="utf-8")
    assert "def run_worker():" in written_code
    ast.parse(written_code)
