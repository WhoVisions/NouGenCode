"""Command-line interface for NouGenCode."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .models import ScanSummary
from .scanners.ast_scanner import AstDeadCodeScanner
from .scanners.orphan_scanner import OrphanFileScanner
from .scanners.dep_scanner import DependencyScanner
from .reporters.console import ConsoleReporter
from .shard_recorder import ShardRecorder


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nougencode",
        description="NouGenCode: Fleet AST code cleaner, dead code scanner, and bloat sweeper.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Target directory or file to scan (default: current directory)")
    parser.add_argument("--save-shard", action="store_true", help="Record scan receipt into NouGen shards")
    parser.add_argument("--no-ast", action="store_true", help="Skip AST deadcode scanner")
    parser.add_argument("--no-orphans", action="store_true", help="Skip orphan root script scanner")
    parser.add_argument("--no-deps", action="store_true", help="Skip dependency scanner")
    parser.add_argument("--json", action="store_true", help="Output summary as JSON")

    args = parser.parse_args()
    target_path = Path(args.path).resolve()

    if not target_path.exists():
        sys.stderr.write(f"Error: Path '{target_path}' does not exist.\n")
        return 1

    summary = ScanSummary(
        target_root=str(target_path),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # 1. AST Scanner
    if not args.no_ast:
        ast_scanner = AstDeadCodeScanner()
        if target_path.is_file() and target_path.suffix == ".py":
            summary.files_scanned += 1
            for issue in ast_scanner.scan_file(target_path):
                summary.add_issue(issue)
        elif target_path.is_dir():
            for py_file in target_path.rglob("*.py"):
                if any(p in py_file.parts for p in (".venv", "node_modules", ".git", "__pycache__")):
                    continue
                summary.files_scanned += 1
                for issue in ast_scanner.scan_file(py_file):
                    summary.add_issue(issue)

    # 2. Orphan Scanner
    if not args.no_orphans and target_path.is_dir():
        orphan_scanner = OrphanFileScanner(target_path)
        for issue in orphan_scanner.scan_orphans():
            summary.add_issue(issue)

    # 3. Dependency Scanner
    if not args.no_deps and target_path.is_dir():
        dep_scanner = DependencyScanner(target_path)
        for issue in dep_scanner.scan_dependencies():
            summary.add_issue(issue)

    shard_id = None
    if args.save_shard:
        recorder = ShardRecorder()
        shard_id = recorder.record_scan_receipt(summary)

    if args.json:
        import json
        out = summary.to_dict()
        if shard_id:
            out["shard_id"] = shard_id
        print(json.dumps(out, indent=2))
    else:
        reporter = ConsoleReporter()
        reporter.print_summary(summary, shard_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
