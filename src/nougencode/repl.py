"""Interactive Claude Code-style terminal REPL interface for NouGenCode."""

import os
import sys
from pathlib import Path
from typing import List, Dict

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from .tools import ToolExecutor
from .scanners.ast_scanner import AstDeadCodeScanner
from .scanners.orphan_scanner import OrphanFileScanner
from .scanners.dep_scanner import DependencyScanner
from .model_runner import ModelRunner
from .shard_recorder import ShardRecorder
from .models import ScanSummary


CUSTOM_STYLE = Style.from_dict({
    "prompt": "ansicyan bold",
})


class ReplSession:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.console = Console()
        self.tools = ToolExecutor(self.root_dir)
        self.runner = ModelRunner()
        self.history: List[Dict[str, str]] = []
        self.prompt_session = PromptSession(history=InMemoryHistory())

    def print_banner(self) -> None:
        welcome_md = (
            f"# ⚡ NouGenCode (Interactive Terminal Agent)\n\n"
            f"* **Directory**: `{self.root_dir}`\n"
            f"* **Model**: `{self.runner.model_name}` (Ollama Local)\n"
            f"* **Context Mode**: `ENFORCED (99% Rule)` -> `~/.nougen/context/session.db`\n"
            f"* **Commands**:\n"
            f"  * `/scan` : Run AST deadcode, orphan, and dependency bloat scan\n"
            f"  * `/ctx <query>` : Search NouGen session context & full event outputs\n"
            f"  * `/view <file>` : View file lines (context-clamped)\n"
            f"  * `/grep <pattern>` : Deep search codebase\n"
            f"  * `/bash <cmd>` : Execute shell command (context-guarded)\n"
            f"  * `/shard` : Persist recent scan results into NouGen memory\n"
            f"  * `/help` : List commands\n"
            f"  * `/exit` or `Ctrl+C` : Exit session\n"
        )
        self.console.print(Panel(Markdown(welcome_md), border_style="cyan", title="⚡ NouGenCode", title_align="left"))

    def run_full_scan(self) -> None:
        self.console.print("[cyan]🔍 Running deep codebase scan across AST, orphans, and dependencies...[/]")
        summary = ScanSummary(target_root=str(self.root_dir))

        # 1. AST
        ast_scanner = AstDeadCodeScanner()
        for py_file in self.root_dir.rglob("*.py"):
            if any(p in py_file.parts for p in (".venv", "node_modules", ".git", "__pycache__")):
                continue
            summary.files_scanned += 1
            for issue in ast_scanner.scan_file(py_file):
                summary.add_issue(issue)

        # 2. Orphans
        orphan_scanner = OrphanFileScanner(self.root_dir)
        for issue in orphan_scanner.scan_orphans():
            summary.add_issue(issue)

        # 3. Dependencies
        dep_scanner = DependencyScanner(self.root_dir)
        for issue in dep_scanner.scan_dependencies():
            summary.add_issue(issue)

        # Print HUD table
        table = Table(title="Scan Findings", header_style="bold magenta", border_style="dim")
        table.add_column("Type", style="cyan")
        table.add_column("Location", style="yellow")
        table.add_column("Symbol", style="green")
        table.add_column("Message", style="white")

        for issue in summary.issues[:30]:
            rel_path = Path(issue.file_path).relative_to(self.root_dir) if Path(issue.file_path).is_absolute() else issue.file_path
            table.add_row(issue.issue_type.value, f"{rel_path}:{issue.line_number}", issue.symbol_name, issue.message)

        self.console.print(table)
        self.console.print(f"[bold green]✔ Scanned {summary.files_scanned} files. Found {len(summary.issues)} issues.[/]")

    def start(self) -> None:
        self.print_banner()

        while True:
            try:
                user_input = self.prompt_session.prompt(
                    "nougencode ❯ ",
                    style=CUSTOM_STYLE,
                ).strip()

                if not user_input:
                    continue

                if user_input in ("/exit", "/quit", "exit", "quit"):
                    self.console.print("[yellow]Exiting NouGenCode session. Clean run.[/]")
                    break

                if user_input == "/scan":
                    self.run_full_scan()
                    continue

                if user_input.startswith("/view "):
                    target = user_input[6:].strip()
                    res = self.tools.view_file(target)
                    self.console.print(Panel(res, title=f"File: {target}", border_style="blue"))
                    continue

                if user_input.startswith("/ctx"):
                    query = user_input[4:].strip()
                    if not query:
                        events = self.tools.context_gate.search_context("*", limit=5)
                    else:
                        events = self.tools.context_gate.search_context(query, limit=5)
                    if not events:
                        self.console.print(f"[yellow]No context events matching '{query or '*'}'[/]")
                    else:
                        for ev in events:
                            self.console.print(
                                Panel(
                                    f"[bold cyan]Timestamp:[/] {ev['timestamp']}\n"
                                    f"[bold yellow]Type:[/] {ev['type']}\n\n"
                                    f"{ev['content'][:500]}...",
                                    title=f"Context Event #{ev['id']}",
                                    border_style="magenta",
                                )
                            )
                    continue

                if user_input.startswith("/grep "):
                    pat = user_input[6:].strip()
                    res = self.tools.grep_search(pat)
                    self.console.print(Panel(res, title=f"Grep: {pat}", border_style="green"))
                    continue

                if user_input.startswith("/bash "):
                    cmd = user_input[6:].strip()
                    res = self.tools.run_bash(cmd)
                    self.console.print(Panel(res, title=f"Bash: {cmd}", border_style="yellow"))
                    continue

                if user_input == "/shard":
                    summary = ScanSummary(target_root=str(self.root_dir))
                    recorder = ShardRecorder()
                    sid = recorder.record_scan_receipt(summary)
                    if sid:
                        self.console.print(f"[bold green]✔ Audit receipt logged to Shard:[/] [cyan]{sid}[/]")
                    else:
                        self.console.print("[yellow]Shard logger ran (core or fallback recorded).[/]")
                    continue

                if user_input == "/help":
                    self.print_banner()
                    continue

                # Pass natural language query to Model Runner
                self.console.print("[dim]Thinking...[/dim]")
                self.history.append({"role": "user", "content": user_input})
                reply = self.runner.chat(
                    self.history,
                    system_prompt=(
                        "You are NouGenCode, an expert autonomous terminal AI coding engineer and fleet architect. "
                        "You help the user clean dead code, resolve bloat, audit AST structures, and write robust code. "
                        "Be direct, concise, and provide actionable solutions without boilerplate."
                    ),
                )
                self.history.append({"role": "assistant", "content": reply})
                self.console.print(Markdown(reply))
                self.console.print()

            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[yellow]Session interrupted. Exiting.[/]")
                break
