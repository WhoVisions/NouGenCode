"""Autonomous tools execution engine for NouGenCode agent."""

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class ToolExecutor:
    """Provides file inspection, editing, terminal bash, and search capabilities."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()

    def view_file(self, file_path: str, max_lines: int = 150) -> str:
        target = (self.root_dir / file_path).resolve()
        if not target.exists():
            return f"Error: File '{file_path}' does not exist."
        if not target.is_file():
            return f"Error: '{file_path}' is a directory."
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            sliced = lines[:max_lines]
            res = "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(sliced))
            if total > max_lines:
                res += f"\n... [{total - max_lines} more lines truncated]"
            return res
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, file_path: str, content: str) -> str:
        target = (self.root_dir / file_path).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content.splitlines())} lines to {file_path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def run_bash(self, command: str) -> str:
        try:
            res = subprocess.run(
                ["powershell", "-Command", command],
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = res.stdout
            if res.stderr:
                out += f"\nSTDERR:\n{res.stderr}"
            return out.strip() if out else f"(Process exited with returncode {res.returncode})"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except Exception as e:
            return f"Error executing command: {e}"

    def grep_search(self, pattern: str, glob_pattern: str = "*.py") -> str:
        matches: List[str] = []
        import re
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            for path in self.root_dir.rglob(glob_pattern):
                if any(p in path.parts for p in (".venv", ".git", "node_modules", "__pycache__")):
                    continue
                try:
                    for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines()):
                        if regex.search(line):
                            rel = path.relative_to(self.root_dir)
                            matches.append(f"{rel}:{i+1}: {line.strip()}")
                            if len(matches) >= 30:
                                break
                except Exception:
                    continue
                if len(matches) >= 30:
                    break
            return "\n".join(matches) if matches else "No matches found."
        except Exception as e:
            return f"Grep error: {e}"
