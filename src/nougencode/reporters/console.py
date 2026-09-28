"""Console reporter and rich HUD for NouGenCode."""

import json
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..models import ScanSummary


class ConsoleReporter:
    def __init__(self) -> None:
        self.console = Console()

    def print_summary(self, summary: ScanSummary, shard_id: Optional[str] = None) -> None:
        table = Table(title="NouGenCode Scan Results", show_header=True, header_style="bold cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Location", style="yellow")
        table.add_column("Symbol", style="bold green")
        table.add_column("Message", style="white")

        for issue in summary.issues[:50]:  # Limit output to 50 items for readability
            loc = f"{issue.file_path}:{issue.line_number}"
            table.add_row(issue.issue_type.value, loc, issue.symbol_name, issue.message)

        self.console.print(table)

        summary_text = (
            f"[bold green]Target:[/] {summary.target_root}\n"
            f"[bold green]Files Scanned:[/] {summary.files_scanned}\n"
            f"[bold green]Total Issues Found:[/] {len(summary.issues)}\n"
        )
        for itype, count in summary.issues_by_type.items():
            summary_text += f" • [cyan]{itype}:[/] {count}\n"

        if shard_id:
            summary_text += f"\n[bold yellow]Saved to Shard:[/] {shard_id}"

        self.console.print(Panel(summary_text, title="Audit Summary", expand=False))
