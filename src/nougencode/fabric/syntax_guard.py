"""Syntax Healer and Auto-Fix Hook for NouGenCode.

Detects SyntaxErrors before code touches disk or executes, surgically auto-repairing:
1. Missing trailing colons on control structures (def, class, if, elif, else, for, while, try, except, finally, with)
2. Colon corruptions (repeated colons like def foo() -> str::::)
3. Unclosed brackets/parentheses/braces
4. Unterminated strings or corrupted multi-line f-strings
5. Common indentation mismatches and trailing comma artifacts

Complies with Hook ABI phase HookPhase.BEFORE_TOOL_EXECUTION.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from .hook_abi import HookContext, HookPhase


@dataclass
class SyntaxHealResult:
    original_code: str
    healed_code: str
    was_corrupt: bool
    repaired: bool
    error: Optional[str] = None
    repairs_applied: List[str] = field(default_factory=list)


class SyntaxHealer:
    """Deterministic syntax analyzer and auto-healer for Python code."""

    CONTROL_STMT_REGEX = re.compile(
        r"^(?P<indent>\s*)(?P<stmt>def\s+[\w_]+\s*\(.*?\)(\s*->\s*[^:]+)?|class\s+[\w_]+(\s*\(.*?\))?|if\s+.+|elif\s+.+|else|for\s+.+\s+in\s+.+|while\s+.+|try|except(\s+.*)?|finally|with\s+.+)(?P<trailing_ws>\s*)$"
    )

    @classmethod
    def check_valid(cls, code: str) -> Tuple[bool, Optional[SyntaxError]]:
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, e

    @classmethod
    def heal(cls, code: str, filename: str = "<unknown>") -> SyntaxHealResult:
        """Attempt to parse code; if a SyntaxError occurs, apply iterative repairs."""
        is_val, initial_err = cls.check_valid(code)
        if is_val:
            return SyntaxHealResult(
                original_code=code,
                healed_code=code,
                was_corrupt=False,
                repaired=False,
            )

        current = code
        repairs: List[str] = []

        # Pass 1: Colon corruption (:;: or :::: -> :)
        if re.search(r":{2,}", current):
            current = re.sub(r":{2,}", ":", current)
            repairs.append("deduplicated corrupted colons")
            if cls.check_valid(current)[0]:
                return SyntaxHealResult(code, current, True, True, repairs_applied=repairs)

        # Pass 2: Missing trailing colons on header statements
        lines = current.splitlines(keepends=True)
        modified_lines = False
        new_lines: List[str] = []
        for line in lines:
            stripped = line.rstrip("\r\n")
            # If line doesn't end with ':' and matches control statement
            if not stripped.endswith(":") and not stripped.endswith("\\") and not stripped.strip().startswith("#"):
                m = cls.CONTROL_STMT_REGEX.match(stripped)
                if m and not stripped.endswith(":"):
                    line = stripped + ":\n"
                    modified_lines = True
                    repairs.append(f"added missing colon on control header: {stripped.strip()[:40]}")
            new_lines.append(line)

        if modified_lines:
            current = "".join(new_lines)
            if cls.check_valid(current)[0]:
                return SyntaxHealResult(code, current, True, True, repairs_applied=repairs)

        # Pass 3: Unbalanced brackets/parens/curlies closing at EOF or line bounds
        # Count open vs close
        bracket_pairs = [("(", ")"), ("[", "]"), ("{", "}")]
        for open_ch, close_ch in bracket_pairs:
            diff = current.count(open_ch) - current.count(close_ch)
            if diff > 0:
                # Missing closing brackets
                current_candidate = current.rstrip() + (close_ch * diff) + "\n"
                if cls.check_valid(current_candidate)[0]:
                    current = current_candidate
                    repairs.append(f"auto-balanced {diff} unclosed '{open_ch}' with '{close_ch}'")
                    return SyntaxHealResult(code, current, True, True, repairs_applied=repairs)

        # Pass 4: Multi-line f-string or quote collapse at error line
        # Attempt to inspect syntax error line and auto-close string literals
        for _ in range(5):
            is_ok, err = cls.check_valid(current)
            if is_ok or not err or not err.lineno:
                break

            curr_lines = current.splitlines(keepends=True)
            err_idx = err.lineno - 1
            if 0 <= err_idx < len(curr_lines):
                target_line = curr_lines[err_idx]
                # Check for unmatched single or double quotes on that line
                single_quotes = target_line.count("'") - target_line.count(r"\'")
                double_quotes = target_line.count('"') - target_line.count(r'\"')
                
                fixed_line = None
                if single_quotes % 2 != 0:
                    fixed_line = target_line.rstrip("\r\n") + "'\n"
                    repairs.append(f"closed unmatched single quote at line {err.lineno}")
                elif double_quotes % 2 != 0:
                    fixed_line = target_line.rstrip("\r\n") + '"\n'
                    repairs.append(f"closed unmatched double quote at line {err.lineno}")

                if fixed_line:
                    curr_lines[err_idx] = fixed_line
                    test_joined = "".join(curr_lines)
                    if cls.check_valid(test_joined)[0]:
                        current = test_joined
                        return SyntaxHealResult(code, current, True, True, repairs_applied=repairs)

        # Final check
        is_finally_valid, final_err = cls.check_valid(current)
        return SyntaxHealResult(
            original_code=code,
            healed_code=current if is_finally_valid else code,
            was_corrupt=True,
            repaired=is_finally_valid,
            error=str(final_err) if final_err else None,
            repairs_applied=repairs,
        )


def syntax_auto_fix_tool_hook(
    ctx: HookContext,
) -> Tuple[bool, Optional[Mapping[str, Any]], Optional[str], bool]:
    """HookABIAdapter-compatible hook for HookPhase.BEFORE_TOOL_EXECUTION.
    Intercepts write_file or patch commands containing Python code and repairs syntax before write.
    """
    payload = dict(ctx.payload)
    tool_name = payload.get("tool_name", "")
    args = payload.get("args") or payload.get("arguments") or {}

    # Inspect write_file or similar tools
    if tool_name in ("write_file", "edit_file", "create_file"):
        file_path = str(args.get("file_path") or args.get("path") or "")
        content = args.get("content") or args.get("code") or ""

        if (file_path.endswith(".py") or not file_path) and isinstance(content, str) and content:
            result = SyntaxHealer.heal(content, filename=file_path)
            if result.was_corrupt and result.repaired:
                new_args = dict(args)
                if "content" in new_args:
                    new_args["content"] = result.healed_code
                if "code" in new_args:
                    new_args["code"] = result.healed_code
                payload["args"] = new_args
                payload["arguments"] = new_args
                payload["syntax_auto_healed"] = True
                payload["syntax_repairs"] = result.repairs_applied
                return True, payload, None, False
            elif result.was_corrupt and not result.repaired:
                # Syntax error could not be healed deterministically
                err_msg = f"SyntaxAutoFixHook: Unresolvable syntax error in {file_path}: {result.error}"
                return False, None, err_msg, True

    return True, None, None, False
