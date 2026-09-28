"""Interactive autonomous terminal REPL interface for NouGenCode."""

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
from .shards_bridge import ShardsBridge
from .skills_engine import SkillRegistry, VERBS
from .recurse_engine import RecurseEngine
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
        self.shards_bridge = ShardsBridge()
        self.skill_registry = SkillRegistry()
        self.recurse_engine = RecurseEngine(self.root_dir / "skills")
        self.history: List[Dict[str, str]] = []
        self.prompt_session = PromptSession(history=InMemoryHistory())

    def print_banner(self) -> None:
        welcome_md = (
            f"# ⚡ NouGenCode (Interactive Terminal Agent)\n\n"
            f"* **Directory**: `{self.root_dir}`\n"
            f"* **Model**: `{self.runner.model_name}` (Ollama Local)\n"
            f"* **Context Guard**: `ENFORCED (99% Rule)` -> `~/.nougen/context/session.db`\n"
            f"* **Memory Substrate**: `NouGenShards 9-DB Grid` -> `~/.nougen/shards`\n"
            f"* **Skills Loaded**: `{len(self.skill_registry.skills)} skills discovered`\n"
            f"* **Commands**:\n"
            f"  * `/scan` : Run AST deadcode, orphan, and dependency bloat scan\n"
            f"  * `/skills` : List discovered fleet skills\n"
            f"  * `/skill <name>` : View full instructions for a skill\n"
            f"  * `/create-skill <name>` : Create a new canonical SKILL.md package\n"
            f"  * `/recurse` : Discover & recurse edge tools into skills\n"
            f"  * `/flow <lyrics>` : Analyze rap cadence, metric subdivision, & breath architecture\n"
            f"  * `/verbs` : View 11-verb cognitive instruction set\n"
            f"  * `/recall <query>` : Search 9-DB NouGenShards memory substrate\n"
            f"  * `/ctx <query>` : Search NouGen session context & tool events\n"
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

                if user_input == "/skills":
                    skills = self.skill_registry.list_skills()
                    if not skills:
                        self.console.print("[yellow]No skills currently found in skill directories.[/]")
                    else:
                        table = Table(title="Discovered Fleet Skills", header_style="bold cyan")
                        table.add_column("Skill Name", style="bold green")
                        table.add_column("Description", style="white")
                        for s in skills[:30]:
                            table.add_row(s.name, s.description[:80])
                        self.console.print(table)
                    continue

                if user_input.startswith("/skill "):
                    sname = user_input[7:].strip()
                    sk = self.skill_registry.get_skill(sname)
                    if not sk:
                        self.console.print(f"[yellow]Skill '{sname}' not found. Run /skills to list available.[/]")
                    else:
                        self.console.print(
                            Panel(
                                Markdown(sk.body[:2500]),
                                title=f"Skill: {sk.name}",
                                border_style="cyan",
                            )
                        )
                    continue

                if user_input.startswith("/create-skill "):
                    sname = user_input[14:].strip()
                    if not sname:
                        self.console.print("[yellow]Usage: /create-skill <skill-name>[/]")
                        continue
                    desc = self.prompt_session.prompt("Enter skill description: ").strip() or "Custom skill"
                    instr = self.prompt_session.prompt("Enter core instruction workflow: ").strip() or "Standard instructions."
                    new_skill = self.skill_registry.create_skill(sname, desc, instr)
                    self.console.print(
                        f"[bold green]✔ Skill '{new_skill.name}' created at:[/] [cyan]{new_skill.path}[/]"
                    )
                    continue

                if user_input == "/recurse":
                    tools = self.recurse_engine.discover_tools()
                    if not tools:
                        self.console.print("[yellow]No edge tools discovered to recurse.[/]")
                    else:
                        table = Table(title="Discovered Edge Tools (Available to Recurse)", header_style="bold green")
                        table.add_column("Tool", style="bold cyan")
                        table.add_column("Lines", style="yellow")
                        table.add_column("Summary", style="white")
                        for t in tools:
                            table.add_row(t["name"], str(t["lines"]), t["doc"][:80])
                        self.console.print(table)
                        self.console.print("[dim]Run /recurse <tool_name> to compile an edge tool into a clean skill package.[/]")
                    continue

                if user_input.startswith("/recurse "):
                    tname = user_input[9:].strip()
                    res = self.recurse_engine.recurse_as_skill(tname)
                    if res:
                        self.skill_registry.reload()
                        self.console.print(f"[bold green]✔ Successfully recursed '{tname}' into skill:[/] [cyan]{res.name}[/]")
                    else:
                        self.console.print(f"[yellow]Could not recurse '{tname}'. Run /recurse to view valid tools.[/]")
                    continue

                if user_input.startswith("/flow"):
                    from .flow_craft import FlowCraftEngine
                    lyrics = user_input[5:].strip()
                    if not lyrics:
                        lyrics = self.prompt_session.prompt("Enter verse lyrics to analyze: ").strip()
                    if not lyrics:
                        self.console.print("[yellow]No lyrics provided for flow analysis.[/]")
                        continue
                    
                    engine = FlowCraftEngine(default_bpm=92)
                    res = engine.analyze_bars(lyrics)
                    table = Table(title=f"Flow Craft & Delivery Analysis (BPM: {res.bpm})", header_style="bold green")
                    table.add_column("Metric", style="bold cyan")
                    table.add_column("Value", style="yellow")
                    table.add_row("Total Bars", str(res.total_bars))
                    table.add_row("Dominant Subdivision", res.dominant_subdivision)
                    table.add_row("Pocket Score", f"{res.pocket_score * 100:.1f}%")
                    table.add_row("Breath Viability", f"{res.breath_viability * 100:.1f}%")
                    table.add_row("Multisyllabic Density", f"{res.multisyllabic_density} per bar")
                    table.add_row("Flow Switches", str(len(res.flow_switches)))
                    self.console.print(table)

                    if res.diagnostics:
                        for d in res.diagnostics:
                            self.console.print(f"[yellow]⚠ {d}[/]")

                    markup = engine.suggest_delivery_markup(lyrics)
                    self.console.print(Panel(markup, title="Performance & Breath Markup", border_style="cyan"))
                    continue

                if user_input == "/verbs":
                    table = Table(title="NouGen 11-Verb Cognitive Architecture", header_style="bold magenta")
                    table.add_column("Verb", style="bold cyan")
                    table.add_column("Plane", style="yellow")
                    table.add_column("Role", style="white")
                    for vname, vdata in VERBS.items():
                        table.add_row(vname, vdata["plane"], vdata["role"])
                    self.console.print(table)
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

                if user_input.startswith("/recall "):
                    query = user_input[8:].strip()
                    self.console.print(f"[cyan]Searching 9-DB NouGenShards for:[/] '{query}'...")
                    shards = self.shards_bridge.search_shards(query, limit=4)
                    if not shards:
                        self.console.print("[yellow]No shards matched query.[/]")
                    else:
                        for s in shards:
                            self.console.print(
                                Panel(
                                    f"[bold green]Title:[/] {s['title']}\n"
                                    f"[bold yellow]Locator:[/] {s['locator']} | [bold cyan]Utility:[/] {s['utility_score']}\n"
                                    f"[bold white]Tags:[/] {s['tags']}\n\n"
                                    f"{s['content'][:400]}...",
                                    title=f"Shard {s['locator']}",
                                    border_style="green",
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
